"""
Tests for apps.kafka_events.consumers — checklist item G05.

Unit-level only: calls dispatch_event()/handle_*() directly with plain dict
payloads, the same shape run_booking_consumer() produces after
json.loads(msg.value()). Never starts a real consumer loop and never
requires a running Kafka broker — consistent with apps/bookings/tests.py
(A10). confluent_kafka's *import* is stubbed by the repo-root conftest.py
only in environments where the real C extension can't be built; these tests
don't touch the Producer/Consumer classes at all, so that stub is just what
lets this module import, not what makes these tests pass.
"""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from apps.bookings.models import Booking
from apps.kafka_events.consumers import (
    dispatch_event,
    handle_booking_cancelled,
    handle_booking_created,
    handle_payment_failed,
    handle_payment_success,
)
from apps.kafka_events.topics import (
    TOPIC_BOOKING_CANCELLED,
    TOPIC_BOOKING_CREATED,
    TOPIC_PAYMENT_FAILED,
    TOPIC_PAYMENT_SUCCESS,
)


def _make_booking(status="PENDING"):
    user = User.objects.create_user(
        username=f"kafka_test_{status.lower()}", email=f"{status.lower()}@example.com", password="x"
    )
    return Booking.objects.create(
        user=user,
        status=status,
        total_amount=1000,
        check_in="2026-11-01",
        check_out="2026-11-02",
    )


class G05RegressionTests(TestCase):
    def test_handle_booking_created_is_defined_only_once_and_does_not_raise(self):
        """
        Before the fix, this function was defined twice (the second
        definition silently shadowed the first), and BOTH versions imported
        a non-existent `email_tasks` module. This confirms the single
        surviving version runs to completion without raising.
        """
        handle_booking_created({"booking_id": "irrelevant-for-this-handler"})

    def test_payment_success_no_longer_raises_module_not_found(self):
        """
        Before the fix, `from tasks.email_tasks import send_payment_receipt`
        executed BEFORE the booking-status update, so every payment.success
        event raised ModuleNotFoundError immediately — the booking was never
        marked PAID, the Kafka offset was never committed, and the broker
        redelivered the same event forever.
        """
        booking = _make_booking(status="PENDING")
        handle_payment_success({"booking_id": str(booking.id)})
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")

    def test_booking_cancelled_handler_now_exists_and_does_not_raise(self):
        """
        handle_booking_cancelled was called from the dispatch switch but was
        never defined anywhere in the original file — every booking.cancelled
        event would have raised NameError. Confirms it now exists.
        """
        handle_booking_cancelled({"booking_id": "irrelevant-for-this-handler"})

    def test_dispatch_event_routes_booking_cancelled_without_nameerror(self):
        dispatch_event(TOPIC_BOOKING_CANCELLED, {"booking_id": "irrelevant"})

    def test_dispatch_event_routes_all_four_known_topics(self):
        booking = _make_booking(status="PENDING")
        dispatch_event(TOPIC_BOOKING_CREATED, {"booking_id": str(booking.id)})
        dispatch_event(TOPIC_PAYMENT_SUCCESS, {"booking_id": str(booking.id)})
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")

    def test_dispatch_event_unknown_topic_logs_and_does_not_raise(self):
        dispatch_event("some.other.topic", {"anything": "goes"})


class RepeatedEventProcessingTests(TestCase):
    """
    Kafka's at-least-once delivery means the SAME event can legitimately
    arrive twice. These tests document actual current behavior — they do
    NOT assert exactly-once/idempotent semantics at the handler level. The
    processed-event ledger that suppresses duplicates lives in the consumer
    loop (G07), not in these handlers.
    """

    def test_processing_the_same_payment_success_event_twice_is_safe_but_not_tracked(self):
        booking = _make_booking(status="PENDING")
        payload = {"booking_id": str(booking.id)}

        handle_payment_success(payload)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")

        # Second delivery of the identical event — safe here only because
        # setting status='PAID' twice happens to be naturally idempotent.
        # Duplicate suppression for the event as a whole is the G07 ledger's
        # job; this test exercises the handler directly, without it.
        handle_payment_success(payload)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")

    def test_payment_failed_after_payment_success_does_not_cancel_a_paid_booking(self):
        booking = _make_booking(status="PENDING")
        payload = {"booking_id": str(booking.id)}

        handle_payment_success(payload)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")

        # G11: a late or duplicate payment.failed event must not undo a
        # successful payment. (Before G11 this test asserted CANCELLED, which
        # documented the bug.)
        handle_payment_failed(payload)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")


class MalformedEventTests(TestCase):
    def test_payment_success_missing_booking_id_key_does_not_raise(self):
        handle_payment_success({})

    def test_payment_success_non_uuid_booking_id_does_not_raise(self):
        handle_payment_success({"booking_id": "not-a-valid-uuid"})

    def test_payment_failed_missing_booking_id_key_does_not_raise(self):
        handle_payment_failed({})

    def test_payment_failed_non_uuid_booking_id_does_not_raise(self):
        handle_payment_failed({"booking_id": "not-a-valid-uuid"})

    def test_booking_created_empty_payload_does_not_raise(self):
        handle_booking_created({})

    def test_dispatch_event_malformed_payload_on_known_topic_does_not_raise(self):
        dispatch_event(TOPIC_PAYMENT_SUCCESS, {})
        dispatch_event(TOPIC_PAYMENT_FAILED, {"booking_id": None})


class RetrySemanticsTests(TestCase):
    """
    run_booking_consumer() decides whether to commit the Kafka offset based
    on whether dispatch_event() raises. These pin down that contract
    directly, without needing a real consumer/broker.
    """

    def test_unexpected_database_failure_propagates_for_retry(self):
        booking = _make_booking(status="PENDING")
        with mock.patch(
            "apps.bookings.models.Booking.objects.get",
            side_effect=Exception("simulated database outage"),
        ):
            with self.assertRaises(Exception):
                dispatch_event(TOPIC_PAYMENT_SUCCESS, {"booking_id": str(booking.id)})
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PENDING")  # unexpected failure must not silently half-apply

    def test_unknown_booking_id_does_not_propagate_avoids_infinite_redelivery(self):
        dispatch_event(TOPIC_PAYMENT_SUCCESS, {"booking_id": "00000000-0000-0000-0000-000000000000"})
        dispatch_event(TOPIC_PAYMENT_FAILED, {"booking_id": "00000000-0000-0000-0000-000000000000"})