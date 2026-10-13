"""
Tests for the G03 reliability behaviour of the email tasks.

Tasks are called directly (synchronously). Retry *scheduling* (backoff
delays, the broker re-queueing) is not exercised here; that needs a running
worker and is part of the later testing phase. These tests check the retry
configuration, failure handling, and duplicate suppression.
"""
import logging
import uuid
from decimal import Decimal
from unittest import mock

from celery.exceptions import SoftTimeLimitExceeded
from django.contrib.auth.models import User
from django.core import mail
from django.db import IntegrityError, OperationalError, transaction
from django.test import TestCase

from apps.bookings.models import Booking, BookingItem, EmailNotification
from apps.bookings.tasks import send_booking_confirmation, send_payment_receipt


def _make_booking(status="PENDING", email="guest@example.com", username="guest"):
    user = User.objects.create_user(username=username, email=email, password="x")
    booking = Booking.objects.create(
        user=user,
        status=status,
        total_amount=Decimal("4500.00"),
        check_in="2026-11-01",
        check_out="2026-11-03",
    )
    BookingItem.objects.create(
        booking=booking,
        item_type="HOTEL",
        item_id=uuid.uuid4(),
        item_name="Seaside Resort",
        price_at_booking=Decimal("2250.00"),
        quantity=1,
        nights=2,
    )
    return booking


class RetryAndTimeoutConfigurationTests(TestCase):
    def test_retries_are_bounded(self):
        for task in (send_booking_confirmation, send_payment_receipt):
            self.assertEqual(task.max_retries, 5)

    def test_exponential_backoff_is_enabled_and_capped(self):
        for task in (send_booking_confirmation, send_payment_receipt):
            self.assertTrue(task.retry_backoff)
            self.assertEqual(task.retry_backoff_max, 300)
            self.assertTrue(task.retry_jitter)

    def test_transient_error_types_are_retried(self):
        for task in (send_booking_confirmation, send_payment_receipt):
            for exc in (OSError, OperationalError, SoftTimeLimitExceeded):
                self.assertIn(exc, task.autoretry_for)

    def test_time_limits_are_set(self):
        for task in (send_booking_confirmation, send_payment_receipt):
            self.assertEqual(task.soft_time_limit, 30)
            self.assertEqual(task.time_limit, 60)
            self.assertLess(task.soft_time_limit, task.time_limit)

    def test_tasks_acknowledge_late(self):
        for task in (send_booking_confirmation, send_payment_receipt):
            self.assertTrue(task.acks_late)


class DuplicateSuppressionTests(TestCase):
    def test_confirmation_sent_twice_is_delivered_once(self):
        booking = _make_booking()
        self.assertEqual(send_booking_confirmation(str(booking.id)), "sent")
        self.assertEqual(send_booking_confirmation(str(booking.id)), "skipped:already-sent")
        self.assertEqual(len(mail.outbox), 1)
        record = EmailNotification.objects.get(booking=booking, kind="CONFIRMATION")
        self.assertEqual(record.status, "SENT")
        self.assertIsNotNone(record.sent_at)

    def test_receipt_sent_twice_is_delivered_once(self):
        booking = _make_booking(status="PAID")
        self.assertEqual(send_payment_receipt(str(booking.id)), "sent")
        self.assertEqual(send_payment_receipt(str(booking.id)), "skipped:already-sent")
        self.assertEqual(len(mail.outbox), 1)

    def test_confirmation_and_receipt_are_tracked_separately(self):
        booking = _make_booking(status="PENDING")
        send_booking_confirmation(str(booking.id))
        booking.status = "PAID"
        booking.save(update_fields=["status"])
        send_payment_receipt(str(booking.id))
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(EmailNotification.objects.filter(booking=booking).count(), 2)

    def test_database_rejects_a_second_record_for_the_same_booking_and_kind(self):
        booking = _make_booking()
        EmailNotification.objects.create(booking=booking, kind="CONFIRMATION")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EmailNotification.objects.create(booking=booking, kind="CONFIRMATION")

    def test_skipped_cases_do_not_create_records(self):
        no_email = _make_booking(email="", username="noemail")
        cancelled = _make_booking(status="CANCELLED", username="cancelled")
        pending = _make_booking(status="PENDING", username="pending")
        send_booking_confirmation(str(no_email.id))
        send_booking_confirmation(str(cancelled.id))
        send_payment_receipt(str(pending.id))
        send_booking_confirmation(str(uuid.uuid4()))
        self.assertEqual(EmailNotification.objects.count(), 0)


class TransientFailureTests(TestCase):
    def test_send_failure_propagates_and_is_not_recorded_as_sent(self):
        booking = _make_booking()
        with mock.patch("apps.bookings.tasks.send_mail", side_effect=OSError("smtp down")):
            with self.assertRaises(OSError):
                send_booking_confirmation(str(booking.id))
        self.assertFalse(
            EmailNotification.objects.filter(booking=booking, status="SENT").exists()
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_a_retry_after_a_failure_sends_exactly_one_email(self):
        booking = _make_booking()
        with mock.patch("apps.bookings.tasks.send_mail", side_effect=OSError("smtp down")):
            with self.assertRaises(OSError):
                send_booking_confirmation(str(booking.id))
        self.assertEqual(send_booking_confirmation(str(booking.id)), "sent")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailNotification.objects.filter(booking=booking, status="SENT").count(), 1)


class PermanentFailureLoggingTests(TestCase):
    def test_on_failure_logs_the_task_name_and_arguments(self):
        with self.assertLogs("apps.bookings.tasks", level=logging.ERROR) as captured:
            send_booking_confirmation.on_failure(
                OSError("smtp down"), "task-id-123", ("booking-abc",), {}, None
            )
        joined = "\n".join(captured.output)
        self.assertIn("failed permanently", joined)
        self.assertIn("booking-abc", joined)
        self.assertIn("task-id-123", joined)