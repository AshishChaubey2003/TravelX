"""
Tests that the Kafka consumer handlers queue the G02 email tasks.

Most tests patch `.delay` to check *what is queued*; the last test uses the
in-process Celery mode from conftest.py to check the full path produces a
real (in-memory) email. None of this talks to a real Kafka broker, Redis, or
SMTP server.
"""
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase

from apps.bookings.models import Booking
from apps.bookings.tasks import send_booking_confirmation, send_payment_receipt
from apps.kafka_events.consumers import (
    dispatch_event,
    handle_booking_created,
    handle_payment_failed,
    handle_payment_success,
)
from apps.kafka_events.topics import TOPIC_PAYMENT_SUCCESS


def _make_booking(status="PENDING"):
    user = User.objects.create_user(
        username=f"wiring_{status.lower()}", email=f"{status.lower()}@example.com", password="x"
    )
    return Booking.objects.create(
        user=user,
        status=status,
        total_amount=1000,
        check_in="2026-11-01",
        check_out="2026-11-02",
    )


class ConsumerQueuesEmailTasksTests(TestCase):
    def test_booking_created_queues_confirmation_with_booking_id(self):
        with mock.patch.object(send_booking_confirmation, "delay") as delay:
            handle_booking_created({"booking_id": "abc-123"})
        delay.assert_called_once_with("abc-123")

    def test_booking_created_without_booking_id_queues_nothing(self):
        with mock.patch.object(send_booking_confirmation, "delay") as delay:
            handle_booking_created({})
        delay.assert_not_called()

    def test_payment_success_marks_paid_and_queues_receipt(self):
        booking = _make_booking(status="PENDING")
        with mock.patch.object(send_payment_receipt, "delay") as delay:
            handle_payment_success({"booking_id": str(booking.id)})
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")
        delay.assert_called_once_with(str(booking.id))

    def test_payment_success_for_unknown_booking_queues_nothing(self):
        with mock.patch.object(send_payment_receipt, "delay") as delay:
            handle_payment_success({"booking_id": "00000000-0000-0000-0000-000000000000"})
        delay.assert_not_called()

    def test_payment_failed_queues_no_email(self):
        booking = _make_booking(status="PENDING")
        with mock.patch.object(send_payment_receipt, "delay") as receipt, \
                mock.patch.object(send_booking_confirmation, "delay") as confirmation:
            handle_payment_failed({"booking_id": str(booking.id)})
        receipt.assert_not_called()
        confirmation.assert_not_called()

    def test_broker_failure_propagates_so_the_event_is_redelivered(self):
        booking = _make_booking(status="PENDING")
        with mock.patch.object(
            send_payment_receipt, "delay", side_effect=ConnectionError("broker down")
        ):
            with self.assertRaises(ConnectionError):
                dispatch_event(TOPIC_PAYMENT_SUCCESS, {"booking_id": str(booking.id)})
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")  # status was saved before the enqueue failed


class EndToEndInProcessTests(TestCase):
    def test_payment_success_event_results_in_a_receipt_email(self):
        booking = _make_booking(status="PENDING")
        dispatch_event(TOPIC_PAYMENT_SUCCESS, {"booking_id": str(booking.id)})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [booking.user.email])
        self.assertIn("receipt", mail.outbox[0].subject.lower())