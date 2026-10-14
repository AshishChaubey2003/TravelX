"""
F-005 — expiry sweep tests.

HONESTY NOTE: the TestCase classes run on SQLite, which ignores
SELECT ... FOR UPDATE. They prove the sweep's RECHECK LOGIC (status,
cutoff, Payment existence inside the per-booking transaction) and its
transactional rollback — never real lock serialisation. The race tests in
PostgresSweepRaceTests skip unless the database is PostgreSQL and are
BLOCKED until run there.
"""
import threading
from datetime import timedelta
from unittest import mock, skipUnless

from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.bookings.models import Booking
from apps.bookings.services import BookingService
from apps.bookings.tasks_expiry import (
    _cutoff,
    _expire_one_booking,
    expire_stale_pending_bookings,
)
from apps.bookings.test_services import (
    _make_city,
    _make_hotel,
    _make_user,
)
from apps.payments.models import Payment


def _backdate(booking, minutes):
    Booking.objects.filter(pk=booking.pk).update(
        created_at=timezone.now() - timedelta(minutes=minutes))
    booking.refresh_from_db()


class ExpirySweepRuleTests(TestCase):
    def setUp(self):
        self.city = _make_city()
        self.user = _make_user("expiry_user")
        self.hotel = _make_hotel(self.city, total_rooms=5, available_rooms=5)

    def _service_booking(self, check_in="2026-11-01", check_out="2026-11-03"):
        return BookingService.create_booking(self.user, {
            "hotel_id": str(self.hotel.id),
            "check_in": check_in, "check_out": check_out,
        })

    def test_old_pending_booking_without_payment_is_expired_and_released(self):
        booking = self._service_booking()
        self.hotel.refresh_from_db()
        self.assertEqual(self.hotel.available_rooms, 4)  # reserved
        _backdate(booking, 31)

        summary = expire_stale_pending_bookings()

        self.assertEqual(summary, {"expired": 1, "skipped": 0, "failed": 0})
        booking.refresh_from_db()
        self.hotel.refresh_from_db()
        self.assertEqual(booking.status, "CANCELLED")
        self.assertEqual(self.hotel.available_rooms, 5)  # released atomically

    def test_recent_pending_booking_is_retained(self):
        booking = self._service_booking()
        _backdate(booking, 29)  # inside the 30-minute default window
        summary = expire_stale_pending_bookings()
        booking.refresh_from_db()
        self.assertEqual(summary["expired"], 0)
        self.assertEqual(booking.status, "PENDING")

    def test_non_pending_booking_is_retained(self):
        booking = self._service_booking()
        Booking.objects.filter(pk=booking.pk).update(status="PAID")
        _backdate(booking, 999)
        summary = expire_stale_pending_bookings()
        booking.refresh_from_db()
        self.assertEqual(summary["expired"], 0)
        self.assertEqual(booking.status, "PAID")

    def test_booking_with_any_payment_row_is_skipped(self):
        for payment_status in ("PENDING", "FAILED"):
            booking = self._service_booking()
            _backdate(booking, 31)
            Payment.objects.create(
                booking=booking, amount=booking.total_amount,
                currency="inr", status=payment_status,
            )
            summary = expire_stale_pending_bookings()
            booking.refresh_from_db()
            self.assertEqual(summary["expired"], 0,
                             f"payment status {payment_status} must exempt")
            self.assertEqual(booking.status, "PENDING")
            booking.payment.delete()
            Booking.objects.filter(pk=booking.pk).update(status="CANCELLED")

    def test_payment_created_between_select_and_lock_exempts_booking(self):
        """The critical recheck (M13 §2.4): the booking already passed the
        unlocked candidate query; a Payment then appears BEFORE the sweep
        locks it. The in-transaction recheck must skip it."""
        booking = self._service_booking()
        _backdate(booking, 31)
        cutoff = _cutoff()
        # Candidate query would have selected it:
        self.assertIn(
            booking.pk,
            list(Booking.objects.filter(
                status="PENDING", created_at__lt=cutoff, payment__isnull=True,
            ).values_list("pk", flat=True)),
        )
        # ... and now checkout starts:
        Payment.objects.create(booking=booking, amount=booking.total_amount,
                               currency="inr", status="PENDING")
        outcome = _expire_one_booking(booking.pk, cutoff)
        booking.refresh_from_db()
        self.assertEqual(outcome, "skipped:has-payment")
        self.assertEqual(booking.status, "PENDING")

    def test_locked_get_reasserts_pending_status(self):
        booking = self._service_booking()
        _backdate(booking, 31)
        cutoff = _cutoff()
        Booking.objects.filter(pk=booking.pk).update(status="PAID")  # won the race
        self.assertEqual(_expire_one_booking(booking.pk, cutoff), "skipped:not-pending")

    def test_repeated_sweep_is_idempotent(self):
        booking = self._service_booking()
        _backdate(booking, 31)
        first = expire_stale_pending_bookings()
        second = expire_stale_pending_bookings()
        self.assertEqual(first["expired"], 1)
        self.assertEqual(second, {"expired": 0, "skipped": 0, "failed": 0})
        self.hotel.refresh_from_db()
        self.assertEqual(self.hotel.available_rooms, 5)  # released exactly once

    def test_release_failure_rolls_back_cancellation(self):
        booking = self._service_booking()
        _backdate(booking, 31)
        with mock.patch.object(BookingService, "release_inventory",
                               side_effect=RuntimeError("boom")):
            summary = expire_stale_pending_bookings()
        booking.refresh_from_db()
        self.hotel.refresh_from_db()
        self.assertEqual(summary, {"expired": 0, "skipped": 0, "failed": 1})
        self.assertEqual(booking.status, "PENDING")   # cancel rolled back too
        self.assertEqual(self.hotel.available_rooms, 4)  # still reserved

    def test_booking_cancelled_by_another_path_is_not_released_again(self):
        booking = self._service_booking()
        _backdate(booking, 31)
        # Another path (e.g. BookingCancelView) cancels + releases first:
        with transaction.atomic():
            locked = Booking.objects.select_for_update().get(pk=booking.pk)
            BookingService.release_inventory(locked)
            locked.status = "CANCELLED"
            locked.save(update_fields=["status"])
        self.hotel.refresh_from_db()
        self.assertEqual(self.hotel.available_rooms, 5)

        summary = expire_stale_pending_bookings()
        self.hotel.refresh_from_db()
        self.assertEqual(summary["expired"], 0)
        self.assertEqual(self.hotel.available_rooms, 5)  # NOT released twice

    @override_settings(BOOKING_PENDING_EXPIRY_MINUTES=5)
    def test_cutoff_is_configurable(self):
        booking = self._service_booking()
        _backdate(booking, 6)
        summary = expire_stale_pending_bookings()
        booking.refresh_from_db()
        self.assertEqual(summary["expired"], 1)
        self.assertEqual(booking.status, "CANCELLED")

    def test_explicit_minutes_argument_overrides_setting(self):
        booking = self._service_booking()
        _backdate(booking, 10)
        self.assertEqual(expire_stale_pending_bookings(minutes=60)["expired"], 0)
        self.assertEqual(expire_stale_pending_bookings(minutes=5)["expired"], 1)


@skipUnless(connection.vendor == "postgresql",
            "Race behaviour needs real SELECT FOR UPDATE — PostgreSQL only; "
            "BLOCKED in this workspace, runnable via WINDOWS_SETUP.md.")
class PostgresSweepRaceTests(TransactionTestCase):
    """checkout-vs-sweep and payment-event-vs-sweep under real row locks."""

    def setUp(self):
        self.city = _make_city()
        self.user = _make_user("expiry_pg")
        self.hotel = _make_hotel(self.city, total_rooms=5, available_rooms=5)
        self.booking = BookingService.create_booking(self.user, {
            "hotel_id": str(self.hotel.id),
            "check_in": "2026-11-01", "check_out": "2026-11-03",
        })
        _backdate(self.booking, 31)

    def _race(self, call_a, call_b):
        barrier = threading.Barrier(2, timeout=10)
        results = {}

        def runner(name, fn):
            try:
                barrier.wait()
                results[name] = ("ok", fn())
            except Exception as exc:  # noqa: BLE001
                results[name] = ("err", exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=runner, args=(n, f))
                   for n, f in (("a", call_a), ("b", call_b))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        return results

    def test_checkout_vs_sweep_never_cancels_a_booking_with_a_payment(self):
        from apps.payments.services import RazorpayService

        fake_order = {"id": "order_race", "amount": 100000, "currency": "INR"}

        def checkout():
            with mock.patch("apps.payments.services.razorpay_client") as client:
                client.order.create.return_value = fake_order
                return RazorpayService.create_order(self.booking)

        def sweep():
            return _expire_one_booking(self.booking.pk, _cutoff())

        self._race(checkout, sweep)
        self.booking.refresh_from_db()
        has_payment = Payment.objects.filter(booking=self.booking).exists()
        if self.booking.status == "CANCELLED":
            self.assertFalse(has_payment, "sweep must never cancel a paid-for booking")
        else:
            self.assertEqual(self.booking.status, "PENDING")
            self.assertTrue(has_payment)

    def test_payment_failed_event_vs_sweep_releases_inventory_exactly_once(self):
        from apps.kafka_events.consumers import handle_payment_failed

        def consumer():
            handle_payment_failed({"booking_id": str(self.booking.pk)})

        def sweep():
            return _expire_one_booking(self.booking.pk, _cutoff())

        self._race(consumer, sweep)
        self.booking.refresh_from_db()
        self.hotel.refresh_from_db()
        self.assertEqual(self.booking.status, "CANCELLED")
        self.assertEqual(self.hotel.available_rooms, 5)  # exactly one release
