import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.db.utils import OperationalError
from django.test import TestCase, override_settings
from django.utils import timezone
from prometheus_client import REGISTRY
from rest_framework.test import APIClient

from apps.bookings.models import Booking
from apps.core import flow_health, monitoring
from apps.core.flow_health import FlowHealthCollector, check_flow_health, record_flow
from apps.core.monitoring import ThresholdExceeded
from apps.payments.models import Payment


def _count(flow, outcome):
    return (
        REGISTRY.get_sample_value(
            "travelx_flow_events_total", {"flow": flow, "outcome": outcome}
        )
        or 0
    )


def _samples(collector):
    out = {}
    for family in collector.collect():
        for sample in family.samples:
            out[(sample.name, tuple(sorted(sample.labels.items())))] = sample.value
    return out


def _user(username="flowuser"):
    return User.objects.create_user(username, f"{username}@example.com", "pass12345")


def _booking(user, status="PENDING", age_minutes=0):
    booking = Booking.objects.create(
        user=user,
        status=status,
        total_amount=Decimal("100.00"),
        check_in=date(2030, 1, 1),
        check_out=date(2030, 1, 2),
    )
    if age_minutes:
        Booking.objects.filter(pk=booking.pk).update(
            created_at=timezone.now() - timedelta(minutes=age_minutes)
        )
    return booking


def _payment(booking, status="PENDING", age_minutes=0, **extra):
    payment = Payment.objects.create(
        booking=booking, amount=Decimal("100.00"), status=status, **extra
    )
    if age_minutes:
        Payment.objects.filter(pk=payment.pk).update(
            created_at=timezone.now() - timedelta(minutes=age_minutes)
        )
    return payment


class RecordFlowTests(TestCase):
    def test_success_counts_and_logs_info_with_allowed_fields(self):
        before = _count("booking_create", "success")
        with self.assertLogs("travelx.flow", level="INFO") as logs:
            record_flow("booking_create", "success", booking_id="b-1")
        self.assertEqual(_count("booking_create", "success"), before + 1)
        record = logs.records[0]
        self.assertEqual(record.levelname, "INFO")
        self.assertEqual(record.flow, "booking_create")
        self.assertEqual(record.outcome, "success")
        self.assertEqual(record.booking_id, "b-1")

    def test_rejected_logs_a_warning(self):
        before = _count("refund", "rejected")
        with self.assertLogs("travelx.flow", level="WARNING") as logs:
            record_flow("refund", "rejected", reason="booking_not_found")
        self.assertEqual(logs.records[0].levelname, "WARNING")
        self.assertEqual(_count("refund", "rejected"), before + 1)

    def test_failure_logs_an_error_with_the_traceback(self):
        before = _count("payment_verify", "failure")
        with self.assertLogs("travelx.flow", level="ERROR") as logs:
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                record_flow("payment_verify", "failure", reason="RuntimeError", exc_info=True)
        self.assertEqual(logs.records[0].levelname, "ERROR")
        self.assertTrue(logs.records[0].exc_info)
        self.assertEqual(_count("payment_verify", "failure"), before + 1)

    def test_fields_outside_the_allowlist_are_dropped(self):
        with self.assertLogs("travelx.flow", level="INFO") as logs:
            record_flow(
                "payment_verify", "rejected",
                razorpay_signature="s3cr3t-sig", user_email="a@b.c", reason="invalid_signature",
            )
        record = logs.records[0]
        self.assertFalse(hasattr(record, "razorpay_signature"))
        self.assertFalse(hasattr(record, "user_email"))
        self.assertNotIn("s3cr3t-sig", "\n".join(logs.output))
        self.assertEqual(record.reason, "invalid_signature")

    def test_unknown_flow_or_outcome_is_ignored_without_raising(self):
        with self.assertLogs("travelx.flow", level="ERROR"):
            record_flow("not_a_flow", "success")
        self.assertIsNone(
            REGISTRY.get_sample_value(
                "travelx_flow_events_total", {"flow": "not_a_flow", "outcome": "success"}
            )
        )

    def test_recording_never_raises_even_if_the_counter_breaks(self):
        with mock.patch.object(flow_health, "FLOW_EVENTS") as fake:
            fake.labels.side_effect = RuntimeError("counter broke")
            with self.assertLogs("travelx.flow", level="WARNING"):
                record_flow("booking_create", "success")  # must not raise


class FlowHealthCollectorTests(TestCase):
    def setUp(self):
        self.user = _user()

    def test_describe_is_empty_so_registration_never_hits_the_database(self):
        self.assertEqual(FlowHealthCollector().describe(), [])

    def test_empty_database_reports_zeros_for_every_label(self):
        samples = _samples(FlowHealthCollector())
        self.assertEqual(samples[("travelx_flow_metrics_up", ())], 1)
        for status in flow_health.BOOKING_STATUSES:
            self.assertEqual(samples[("travelx_bookings", (("status", status),))], 0)
        for status in flow_health.PAYMENT_STATUSES:
            self.assertEqual(samples[("travelx_payments", (("status", status),))], 0)
        self.assertEqual(samples[("travelx_bookings_pending_stale", ())], 0)

    def test_counts_bookings_and_payments_by_status(self):
        _booking(self.user, "PENDING")
        _booking(self.user, "PENDING")
        paid = _booking(self.user, "PAID")
        _payment(paid, "SUCCESS")
        samples = _samples(FlowHealthCollector())
        self.assertEqual(samples[("travelx_bookings", (("status", "PENDING"),))], 2)
        self.assertEqual(samples[("travelx_bookings", (("status", "PAID"),))], 1)
        self.assertEqual(samples[("travelx_payments", (("status", "SUCCESS"),))], 1)

    @override_settings(FLOW_PENDING_STALE_MINUTES=30)
    def test_stale_bookings_respect_the_window(self):
        _booking(self.user, "PENDING", age_minutes=5)
        _booking(self.user, "PENDING", age_minutes=60)
        _booking(self.user, "PAID", age_minutes=600)  # not pending: never stale
        samples = _samples(FlowHealthCollector())
        self.assertEqual(samples[("travelx_bookings_pending_stale", ())], 1)

    @override_settings(FLOW_PENDING_STALE_MINUTES=30)
    def test_stale_payments_respect_the_window(self):
        _payment(_booking(self.user), "PENDING", age_minutes=5)
        _payment(_booking(self.user), "PENDING", age_minutes=90)
        samples = _samples(FlowHealthCollector())
        self.assertEqual(samples[("travelx_payments_pending_stale", ())], 1)

    def test_paid_booking_without_a_payment_is_flagged(self):
        _booking(self.user, "PAID")
        samples = _samples(FlowHealthCollector())
        key = ("travelx_flow_inconsistencies",
               (("kind", "paid_booking_without_successful_payment"),))
        self.assertEqual(samples[key], 1)

    def test_paid_booking_with_successful_payment_is_consistent(self):
        _payment(_booking(self.user, "PAID"), "SUCCESS")
        samples = _samples(FlowHealthCollector())
        for kind in ("paid_booking_without_successful_payment",
                     "successful_payment_booking_not_paid"):
            self.assertEqual(
                samples[("travelx_flow_inconsistencies", (("kind", kind),))], 0
            )

    def test_successful_payment_on_unpaid_booking_is_flagged(self):
        _payment(_booking(self.user, "PENDING"), "SUCCESS")
        samples = _samples(FlowHealthCollector())
        key = ("travelx_flow_inconsistencies",
               (("kind", "successful_payment_booking_not_paid"),))
        self.assertEqual(samples[key], 1)

    def test_successful_payment_on_cancelled_booking_is_not_flagged(self):
        # A refunded booking legitimately ends CANCELLED.
        _payment(_booking(self.user, "CANCELLED"), "SUCCESS")
        samples = _samples(FlowHealthCollector())
        key = ("travelx_flow_inconsistencies",
               (("kind", "successful_payment_booking_not_paid"),))
        self.assertEqual(samples[key], 0)

    def test_database_failure_does_not_break_the_scrape(self):
        with mock.patch.object(flow_health, "_snapshot", side_effect=OperationalError("db down")):
            samples = _samples(FlowHealthCollector())
        self.assertEqual(samples, {("travelx_flow_metrics_up", ()): 0})


class CheckFlowHealthTests(TestCase):
    def setUp(self):
        self.user = _user()

    def test_healthy_returns_counts(self):
        detail = check_flow_health()
        self.assertEqual(detail["stale_pending_bookings"], 0)
        self.assertEqual(detail["paid_booking_without_successful_payment"], 0)

    def test_inconsistency_raises_with_counts_only(self):
        _booking(self.user, "PAID")
        with self.assertRaises(ThresholdExceeded) as ctx:
            check_flow_health()
        self.assertEqual(ctx.exception.detail["paid_booking_without_successful_payment"], 1)

    @override_settings(FLOW_MAX_STALE_PENDING=1, FLOW_PENDING_STALE_MINUTES=30)
    def test_too_many_stale_pending_bookings_raises(self):
        _booking(self.user, age_minutes=60)
        _booking(self.user, age_minutes=61)
        with self.assertRaises(ThresholdExceeded):
            check_flow_health()

    @override_settings(FLOW_MAX_STALE_PENDING=5, FLOW_PENDING_STALE_MINUTES=30)
    def test_stale_pending_within_the_limit_passes(self):
        _booking(self.user, age_minutes=60)
        self.assertEqual(check_flow_health()["stale_pending_bookings"], 1)

    def test_h04_report_includes_a_non_critical_flows_check(self):
        with mock.patch("apps.core.health.check_broker"), mock.patch(
            "apps.core.health.check_kafka"
        ), mock.patch(
            "apps.core.monitoring.check_celery_workers", return_value={"workers": 1}
        ):
            report = monitoring.collect()
        self.assertEqual(report["checks"]["flows"]["state"], "ok")
        self.assertFalse(report["checks"]["flows"]["critical"])


class FlowInstrumentationTests(TestCase):
    """The views record the right flow/outcome. Gateway calls are mocked."""

    def setUp(self):
        self.user = _user()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    # ----- payment_order -----
    def test_create_order_success(self):
        booking = _booking(self.user)
        before = _count("payment_order", "success")
        order = {"id": "order_1", "amount": 10000, "currency": "INR"}
        with mock.patch("apps.payments.views.RazorpayService.create_order", return_value=order):
            resp = self.client.post(
                "/api/v1/payments/razorpay/create-order/",
                {"booking_id": str(booking.id)}, format="json",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_count("payment_order", "success"), before + 1)

    def test_create_order_unknown_booking_is_rejected(self):
        before = _count("payment_order", "rejected")
        resp = self.client.post(
            "/api/v1/payments/razorpay/create-order/",
            {"booking_id": str(uuid.uuid4())}, format="json",
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(_count("payment_order", "rejected"), before + 1)

    def test_create_order_gateway_error_is_a_failure(self):
        booking = _booking(self.user)
        before = _count("payment_order", "failure")
        with mock.patch(
            "apps.payments.views.RazorpayService.create_order",
            side_effect=RuntimeError("gateway down"),
        ):
            resp = self.client.post(
                "/api/v1/payments/razorpay/create-order/",
                {"booking_id": str(booking.id)}, format="json",
            )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(_count("payment_order", "failure"), before + 1)

    # ----- payment_verify -----
    def test_verify_invalid_signature_is_rejected_and_signature_not_logged(self):
        booking = _booking(self.user)
        before = _count("payment_verify", "rejected")
        with mock.patch(
            "apps.payments.views.RazorpayService.verify_payment", return_value=False
        ), self.assertLogs("travelx.flow", level="WARNING") as logs:
            resp = self.client.post(
                "/api/v1/payments/razorpay/verify/",
                {"razorpay_order_id": "order_1", "razorpay_payment_id": "pay_1",
                 "razorpay_signature": "SIGVALUE-123", "booking_id": str(booking.id)},
                format="json",
            )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(_count("payment_verify", "rejected"), before + 1)
        self.assertNotIn("SIGVALUE-123", "\n".join(logs.output))
        self.assertEqual(logs.records[0].reason, "invalid_signature")

    def test_verify_success_marks_booking_paid(self):
        booking = _booking(self.user)
        _payment(booking, "PENDING", stripe_session_id="order_1")
        before = _count("payment_verify", "success")
        with mock.patch(
            "apps.payments.views.RazorpayService.verify_payment", return_value=True
        ):
            resp = self.client.post(
                "/api/v1/payments/razorpay/verify/",
                {"razorpay_order_id": "order_1", "razorpay_payment_id": "pay_1",
                 "razorpay_signature": "sig", "booking_id": str(booking.id)},
                format="json",
            )
        self.assertEqual(resp.status_code, 200)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")
        self.assertEqual(_count("payment_verify", "success"), before + 1)

    def test_verify_valid_signature_but_no_payment_row_is_a_failure(self):
        booking = _booking(self.user)  # no Payment row
        before = _count("payment_verify", "failure")
        with mock.patch(
            "apps.payments.views.RazorpayService.verify_payment", return_value=True
        ):
            resp = self.client.post(
                "/api/v1/payments/razorpay/verify/",
                {"razorpay_order_id": "order_1", "razorpay_payment_id": "pay_1",
                 "razorpay_signature": "sig", "booking_id": str(booking.id)},
                format="json",
            )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(_count("payment_verify", "failure"), before + 1)

    # ----- refund -----
    def test_refund_success(self):
        booking = _booking(self.user, "PAID")
        _payment(booking, "SUCCESS", stripe_payment_intent_id="pay_1")
        before = _count("refund", "success")
        with mock.patch("apps.payments.views.RazorpayService.initiate_refund"):
            resp = self.client.post(
                "/api/v1/payments/refund/", {"booking_id": str(booking.id)}, format="json"
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_count("refund", "success"), before + 1)

    def test_refund_unknown_booking_is_rejected(self):
        before = _count("refund", "rejected")
        resp = self.client.post(
            "/api/v1/payments/refund/", {"booking_id": str(uuid.uuid4())}, format="json"
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(_count("refund", "rejected"), before + 1)

    def test_refund_without_payment_reference_is_rejected(self):
        booking = _booking(self.user, "PAID")
        _payment(booking, "SUCCESS")  # stripe_payment_intent_id stays empty
        before = _count("refund", "rejected")
        resp = self.client.post(
            "/api/v1/payments/refund/", {"booking_id": str(booking.id)}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(_count("refund", "rejected"), before + 1)

    # ----- booking_cancel -----
    def test_cancel_success(self):
        booking = _booking(self.user)
        before = _count("booking_cancel", "success")
        resp = self.client.post(f"/api/v1/bookings/{booking.id}/cancel/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_count("booking_cancel", "success"), before + 1)

    def test_cancel_already_cancelled_is_rejected(self):
        booking = _booking(self.user, "CANCELLED")
        before = _count("booking_cancel", "rejected")
        resp = self.client.post(f"/api/v1/bookings/{booking.id}/cancel/")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(_count("booking_cancel", "rejected"), before + 1)

    def test_cancel_paid_booking_is_rejected(self):
        booking = _booking(self.user, "PAID")
        before = _count("booking_cancel", "rejected")
        resp = self.client.post(f"/api/v1/bookings/{booking.id}/cancel/")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(_count("booking_cancel", "rejected"), before + 1)

    # ----- booking_create -----
    VALID_BODY = {
        "hotel_id": "11111111-1111-1111-1111-111111111111",
        "check_in": "2030-01-01", "check_out": "2030-01-02", "nights": 1,
    }

    def test_create_invalid_input_is_rejected(self):
        before = _count("booking_create", "rejected")
        resp = self.client.post("/api/v1/bookings/", {}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(_count("booking_create", "rejected"), before + 1)

    def test_create_rule_violation_is_rejected(self):
        before = _count("booking_create", "rejected")
        with mock.patch(
            "apps.bookings.views.BookingService.create_booking",
            side_effect=ValueError("not enough rooms"),
        ):
            resp = self.client.post("/api/v1/bookings/", self.VALID_BODY, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(_count("booking_create", "rejected"), before + 1)

    def test_create_unexpected_error_is_a_failure_and_still_propagates(self):
        before = _count("booking_create", "failure")
        with mock.patch(
            "apps.bookings.views.BookingService.create_booking",
            side_effect=RuntimeError("db exploded"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post("/api/v1/bookings/", self.VALID_BODY, format="json")
        self.assertEqual(_count("booking_create", "failure"), before + 1)

    def test_create_success(self):
        booking = _booking(self.user)
        before = _count("booking_create", "success")
        with mock.patch(
            "apps.bookings.views.BookingService.create_booking", return_value=booking
        ):
            resp = self.client.post("/api/v1/bookings/", self.VALID_BODY, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(_count("booking_create", "success"), before + 1)
