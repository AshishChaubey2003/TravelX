"""
Batch 3 / Stage B regression tests: Razorpay order lifecycle (fixes R1).

The gateway client is always mocked; no real Razorpay call is made. Note: these run on
SQLite, where select_for_update() is a no-op, so they prove the logic and the
race-handling branch but NOT true row-lock concurrency (that needs PostgreSQL).
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.bookings.models import Booking
from apps.payments.models import Payment
from apps.payments.services import PaymentNotPayableError, RazorpayService

CREATE_URL = "/api/v1/payments/razorpay/create-order/"
VERIFY_URL = "/api/v1/payments/razorpay/verify/"
CLIENT_PATH = "apps.payments.services.razorpay_client"


def _order(order_id):
    return {"id": order_id, "amount": 100000, "currency": "INR"}


class OrderLifecycleBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ol_user", email="ol@example.com", password="x")
        self.booking = Booking.objects.create(
            user=self.user, status="PENDING", total_amount=Decimal("1000.00"),
            check_in=date(2030, 1, 1), check_out=date(2030, 1, 3),
        )
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def make_payment(self, status="PENDING", order_id="order_A", amount=Decimal("1000.00")):
        return Payment.objects.create(
            booking=self.booking, amount=amount, currency="inr",
            status=status, stripe_session_id=order_id,
        )

    def create_via_view(self):
        return self.api.post(CREATE_URL, {"booking_id": str(self.booking.id)}, format="json")


class RepeatCreateOrderReuseTests(OrderLifecycleBase):
    def test_repeat_create_order_reuses_the_canonical_order(self):
        with patch(CLIENT_PATH) as gateway:
            gateway.order.create.side_effect = [_order("order_A"), _order("order_B")]
            first = RazorpayService.create_order(self.booking)
            second = RazorpayService.create_order(self.booking)
        self.assertEqual(gateway.order.create.call_count, 1)
        self.assertEqual(first["id"], "order_A")
        self.assertEqual(second["id"], "order_A")
        self.assertEqual(second["amount"], 100000)
        self.assertEqual(second["currency"], "INR")
        self.assertEqual(Payment.objects.filter(booking=self.booking).count(), 1)
        payment = Payment.objects.get(booking=self.booking)
        self.booking.refresh_from_db()
        self.assertEqual(payment.stripe_session_id, "order_A")
        self.assertEqual(self.booking.stripe_session_id, "order_A")

    def test_view_returns_the_same_order_and_the_same_contract_twice(self):
        with patch(CLIENT_PATH) as gateway:
            gateway.order.create.side_effect = [_order("order_A"), _order("order_B")]
            first = self.create_via_view()
            second = self.create_via_view()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(gateway.order.create.call_count, 1)
        expected_keys = {"order_id", "amount", "currency", "key_id",
                         "booking_id", "user_email", "user_name"}
        self.assertEqual(set(first.data), expected_keys)
        self.assertEqual(set(second.data), expected_keys)
        self.assertEqual(first.data["order_id"], second.data["order_id"])
        self.assertEqual(second.data["amount"], 100000)

    def test_verify_accepts_only_the_canonical_order_after_a_repeat(self):
        with patch(CLIENT_PATH) as gateway:
            gateway.order.create.side_effect = [_order("order_A"), _order("order_B")]
            self.create_via_view()
            self.create_via_view()
        body = {"razorpay_payment_id": "pay_1", "razorpay_signature": "sig",
                "booking_id": str(self.booking.id)}
        with patch("apps.payments.views.RazorpayService.verify_payment", return_value=True):
            wrong = self.api.post(VERIFY_URL, {**body, "razorpay_order_id": "order_B"}, format="json")
            self.assertEqual(wrong.status_code, 400)
            self.booking.refresh_from_db()
            self.assertEqual(self.booking.status, "PENDING")
            self.assertEqual(Payment.objects.get(booking=self.booking).status, "PENDING")

            right = self.api.post(VERIFY_URL, {**body, "razorpay_order_id": "order_A"}, format="json")
            self.assertEqual(right.status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "PAID")
        self.assertEqual(Payment.objects.get(booking=self.booking).status, "SUCCESS")

    def test_desynchronised_booking_mirror_is_healed_without_a_gateway_call(self):
        self.make_payment(order_id="order_A")
        Booking.objects.filter(pk=self.booking.pk).update(stripe_session_id="order_B")
        self.booking.refresh_from_db()
        with patch(CLIENT_PATH) as gateway:
            result = RazorpayService.create_order(self.booking)
        gateway.order.create.assert_not_called()
        self.assertEqual(result["id"], "order_A")
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.stripe_session_id, "order_A")

    def test_pending_payment_without_an_order_id_gets_one_and_no_duplicate_row(self):
        Payment.objects.create(
            booking=self.booking, amount=Decimal("1000.00"), currency="inr", status="PENDING")
        with patch(CLIENT_PATH) as gateway:
            gateway.order.create.return_value = _order("order_N")
            result = RazorpayService.create_order(self.booking)
        self.assertEqual(gateway.order.create.call_count, 1)
        self.assertEqual(result["id"], "order_N")
        self.assertEqual(Payment.objects.filter(booking=self.booking).count(), 1)
        self.assertEqual(Payment.objects.get(booking=self.booking).stripe_session_id, "order_N")
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.stripe_session_id, "order_N")

    def test_lost_race_keeps_the_recorded_order_and_discards_the_new_one(self):
        def create_and_lose_the_race(_payload):
            # Simulates another request recording its own order while this one was
            # inside the gateway call.
            Payment.objects.create(
                booking=self.booking, amount=Decimal("1000.00"), currency="inr",
                status="PENDING", stripe_session_id="order_race")
            return _order("order_mine")

        with patch(CLIENT_PATH) as gateway:
            gateway.order.create.side_effect = create_and_lose_the_race
            result = RazorpayService.create_order(self.booking)
        self.assertEqual(result["id"], "order_race")
        self.assertEqual(Payment.objects.filter(booking=self.booking).count(), 1)
        self.assertEqual(Payment.objects.get(booking=self.booking).stripe_session_id, "order_race")
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.stripe_session_id, "order_race")

    def test_gateway_failure_leaves_no_payment_and_no_booking_order(self):
        with patch(CLIENT_PATH) as gateway:
            gateway.order.create.side_effect = RuntimeError("gateway down")
            with self.assertRaises(RuntimeError):
                RazorpayService.create_order(self.booking)
        self.assertFalse(Payment.objects.filter(booking=self.booking).exists())
        self.booking.refresh_from_db()
        self.assertIsNone(self.booking.stripe_session_id)


class NonPayableStatesTests(OrderLifecycleBase):
    def test_captured_payment_never_gets_another_order(self):
        self.make_payment(status="SUCCESS", order_id="order_A")
        with patch(CLIENT_PATH) as gateway:
            with self.assertRaises(PaymentNotPayableError):
                RazorpayService.create_order(self.booking)
            response = self.create_via_view()
        gateway.order.create.assert_not_called()
        self.assertEqual(response.status_code, 400)
        self.assertIn("already been recorded", response.data["error"])
        payment = Payment.objects.get(booking=self.booking)
        self.assertEqual(payment.status, "SUCCESS")
        self.assertEqual(payment.stripe_session_id, "order_A")

    def test_failed_and_refunded_payments_never_get_another_order(self):
        for status in ("FAILED", "REFUND_PENDING", "REFUNDED"):
            with self.subTest(status=status):
                Payment.objects.filter(booking=self.booking).delete()
                self.make_payment(status=status, order_id=f"order_{status}")
                with patch(CLIENT_PATH) as gateway:
                    with self.assertRaises(PaymentNotPayableError):
                        RazorpayService.create_order(self.booking)
                    response = self.create_via_view()
                gateway.order.create.assert_not_called()
                self.assertEqual(response.status_code, 400)
                payment = Payment.objects.get(booking=self.booking)
                self.assertEqual(payment.status, status)
                self.assertEqual(payment.stripe_session_id, f"order_{status}")

    def test_cancelled_booking_gets_no_order(self):
        Booking.objects.filter(pk=self.booking.pk).update(status="CANCELLED")
        self.booking.refresh_from_db()
        with patch(CLIENT_PATH) as gateway:
            with self.assertRaises(PaymentNotPayableError):
                RazorpayService.create_order(self.booking)
            response = self.create_via_view()
        gateway.order.create.assert_not_called()
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Payment.objects.filter(booking=self.booking).exists())

    def test_amount_mismatch_refuses_to_reuse_and_changes_nothing(self):
        self.make_payment(order_id="order_A", amount=Decimal("500.00"))
        with patch(CLIENT_PATH) as gateway:
            with self.assertRaises(PaymentNotPayableError):
                RazorpayService.create_order(self.booking)
        gateway.order.create.assert_not_called()
        payment = Payment.objects.get(booking=self.booking)
        self.assertEqual(payment.stripe_session_id, "order_A")
        self.assertEqual(payment.amount, Decimal("500.00"))