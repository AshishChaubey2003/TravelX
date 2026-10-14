"""
M16 — handle_payment_success locking fix.

The TestCase classes run on SQLite and prove the handler's DECISION LOGIC
(gating on the current row state, manual-review policy, idempotency, receipt
dispatch) and its transactional shape — SQLite ignores SELECT ... FOR UPDATE,
so nothing here proves lock serialisation. The real race lives in
PostgresPaymentSuccessRaceTests, which skips unless the test database is
PostgreSQL (BLOCKED in this workspace; runnable via WINDOWS_SETUP.md).
"""
import threading
from unittest import mock, skipUnless

from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase

from apps.bookings.models import Booking
from apps.bookings.services import BookingService
from apps.bookings.tasks import send_payment_receipt
from apps.bookings.test_services import _make_city, _make_hotel, _make_user
from apps.kafka_events.consumers import (
    handle_payment_failed,
    handle_payment_success,
    process_event_once,
)
from apps.kafka_events.models import ProcessedEvent
from apps.kafka_events.topics import TOPIC_PAYMENT_SUCCESS


def _booked_hotel_booking(user, hotel):
    """A real service booking so inventory is actually reserved."""
    return BookingService.create_booking(user, {
        "hotel_id": str(hotel.id),
        "check_in": "2026-11-01", "check_out": "2026-11-03",
    })


class PaymentSuccessDecisionTests(TestCase):
    def setUp(self):
        self.city = _make_city()
        self.user = _make_user("pay_success_user")
        self.hotel = _make_hotel(self.city, total_rooms=3, available_rooms=3)
        self.booking = _booked_hotel_booking(self.user, self.hotel)

    def _success(self):
        with mock.patch.object(send_payment_receipt, "delay") as delay:
            handle_payment_success({"booking_id": str(self.booking.id)})
        return delay

    def test_eligible_pending_booking_is_marked_paid_and_receipt_queued(self):
        delay = self._success()
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "PAID")
        delay.assert_called_once_with(str(self.booking.id))

    def test_confirmed_booking_is_marked_paid_per_transition_policy(self):
        Booking.objects.filter(pk=self.booking.pk).update(status="CONFIRMED")
        self._success()
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "PAID")

    def test_success_after_user_cancellation_does_not_resurrect_the_booking(self):
        # Cancel exactly the way BookingCancelView does: lock, release,
        # CANCELLED, one transaction. Inventory goes back.
        with transaction.atomic():
            locked = Booking.objects.select_for_update().get(pk=self.booking.pk)
            BookingService.release_inventory(locked)
            locked.status = "CANCELLED"
            locked.save(update_fields=["status"])
        self.hotel.refresh_from_db()
        self.assertEqual(self.hotel.available_rooms, 3)

        delay = self._success()

        self.booking.refresh_from_db()
        self.hotel.refresh_from_db()
        self.assertEqual(self.booking.status, "CANCELLED")   # manual review, not PAID
        self.assertEqual(self.hotel.available_rooms, 3)      # inventory stays released
        delay.assert_not_called()                            # no receipt for a non-PAID booking
        # And the cancelled booking stays OUT of the date-overlap count:
        from datetime import date
        self.assertEqual(
            BookingService._overlap_count("HOTEL", self.hotel.id,
                                          date(2026, 11, 1), date(2026, 11, 3)),
            0,
        )

    def test_success_after_expiry_sweep_cancellation_is_manual_review(self):
        from apps.bookings.tasks_expiry import _cutoff, _expire_one_booking
        from datetime import timedelta
        from django.utils import timezone
        Booking.objects.filter(pk=self.booking.pk).update(
            created_at=timezone.now() - timedelta(minutes=31))
        self.assertEqual(_expire_one_booking(self.booking.pk, _cutoff()), "expired")

        delay = self._success()
        self.booking.refresh_from_db()
        self.hotel.refresh_from_db()
        self.assertEqual(self.booking.status, "CANCELLED")
        self.assertEqual(self.hotel.available_rooms, 3)
        delay.assert_not_called()

    def test_duplicate_success_events_are_idempotent_one_receipt(self):
        payload = {"booking_id": str(self.booking.id)}
        with mock.patch.object(send_payment_receipt, "delay") as delay:
            self.assertTrue(process_event_once(TOPIC_PAYMENT_SUCCESS, payload, "m16-dup"))
            self.assertFalse(process_event_once(TOPIC_PAYMENT_SUCCESS, payload, "m16-dup"))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "PAID")
        self.assertEqual(delay.call_count, 1)
        self.assertEqual(ProcessedEvent.objects.count(), 1)

    def test_redelivered_event_on_an_already_paid_booking_still_queues_receipt(self):
        """Pre-existing behaviour preserved by the fix: a redelivery under a
        NEW event key is a noop on status but still queues the (idempotent)
        receipt task, so a lost receipt can be recovered by replay."""
        self._success()
        delay = self._success()  # second delivery, already PAID
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "PAID")
        delay.assert_called_once_with(str(self.booking.id))

    def test_handler_makes_no_payment_record_changes(self):
        from apps.payments.models import Payment
        self.assertEqual(Payment.objects.count(), 0)
        self._success()
        self.assertEqual(Payment.objects.count(), 0)  # consumer never touches Payment


@skipUnless(connection.vendor == "postgresql",
            "Row-lock serialisation requires PostgreSQL — SQLite ignores "
            "SELECT FOR UPDATE; report as BLOCKED, never as proven.")
class PostgresPaymentSuccessRaceTests(TransactionTestCase):
    """The M16 race, exercised with two real competing transactions and a
    barrier (no sleeps): payment.success vs payment.failed on the same
    PENDING booking. Invariant: the final state is NEVER 'PAID with its
    inventory released' — either the cancel won (CANCELLED + released, and
    the success handler saw CANCELLED under the lock → manual review) or the
    success won (PAID + inventory still held, and the failure handler's
    can_transition gate refused to cancel a PAID booking)."""

    def setUp(self):
        self.city = _make_city()
        self.user = _make_user("pay_race_user")
        self.hotel = _make_hotel(self.city, total_rooms=1, available_rooms=1)
        self.booking = _booked_hotel_booking(self.user, self.hotel)

    def test_success_vs_cancellation_never_yields_paid_with_released_inventory(self):
        barrier = threading.Barrier(2, timeout=10)
        errors = {}

        def run(name, fn):
            try:
                barrier.wait()
                with mock.patch.object(send_payment_receipt, "delay"):
                    fn({"booking_id": str(self.booking.id)})
            except Exception as exc:  # noqa: BLE001 — recorded for the assertion
                errors[name] = exc
            finally:
                connection.close()

        threads = [
            threading.Thread(target=run, args=("success", handle_payment_success)),
            threading.Thread(target=run, args=("failed", handle_payment_failed)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(errors, {})
        self.booking.refresh_from_db()
        self.hotel.refresh_from_db()
        if self.booking.status == "PAID":
            self.assertEqual(self.hotel.available_rooms, 0)  # inventory still held
        else:
            self.assertEqual(self.booking.status, "CANCELLED")
            self.assertEqual(self.hotel.available_rooms, 1)  # released exactly once
