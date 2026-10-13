"""
Tests for apps.bookings.tasks (checklist G02).

Tasks are called directly (synchronously). Django's test runner swaps the
email backend for the in-memory one, so mail.outbox is real captured output
of send_mail() — not a mock — but it does NOT prove delivery through a real
SMTP server.
"""
import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase

from apps.bookings.models import Booking, BookingItem
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


class BookingConfirmationTaskTests(TestCase):
    def test_sends_one_email_to_the_booking_owner(self):
        booking = _make_booking()
        result = send_booking_confirmation(str(booking.id))
        self.assertEqual(result, "sent")
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["guest@example.com"])
        self.assertIn(str(booking.id)[:8], message.subject)

    def test_body_contains_item_dates_and_total(self):
        booking = _make_booking()
        send_booking_confirmation(str(booking.id))
        body = mail.outbox[0].body
        self.assertIn("Seaside Resort", body)
        self.assertIn("2026-11-01", body)
        self.assertIn("2026-11-03", body)
        self.assertIn("4500.00", body)

    def test_unknown_booking_is_skipped_without_raising(self):
        result = send_booking_confirmation(str(uuid.uuid4()))
        self.assertEqual(result, "skipped:booking-not-found")
        self.assertEqual(len(mail.outbox), 0)

    def test_malformed_booking_id_is_skipped_without_raising(self):
        self.assertEqual(send_booking_confirmation("not-a-uuid"), "skipped:booking-not-found")
        self.assertEqual(send_booking_confirmation(None), "skipped:booking-not-found")
        self.assertEqual(len(mail.outbox), 0)

    def test_cancelled_booking_gets_no_confirmation(self):
        booking = _make_booking(status="CANCELLED")
        self.assertEqual(send_booking_confirmation(str(booking.id)), "skipped:cancelled")
        self.assertEqual(len(mail.outbox), 0)

    def test_user_without_email_is_skipped(self):
        booking = _make_booking(email="")
        self.assertEqual(send_booking_confirmation(str(booking.id)), "skipped:no-email")
        self.assertEqual(len(mail.outbox), 0)


class PaymentReceiptTaskTests(TestCase):
    def test_paid_booking_receives_a_receipt(self):
        booking = _make_booking(status="PAID")
        result = send_payment_receipt(str(booking.id))
        self.assertEqual(result, "sent")
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["guest@example.com"])
        self.assertIn("receipt", message.subject.lower())
        self.assertIn("4500.00", message.body)

    def test_unpaid_booking_gets_no_receipt(self):
        booking = _make_booking(status="PENDING")
        self.assertEqual(send_payment_receipt(str(booking.id)), "skipped:not-paid")
        self.assertEqual(len(mail.outbox), 0)

    def test_unknown_booking_is_skipped_without_raising(self):
        self.assertEqual(send_payment_receipt(str(uuid.uuid4())), "skipped:booking-not-found")
        self.assertEqual(len(mail.outbox), 0)

    def test_user_without_email_is_skipped(self):
        booking = _make_booking(status="PAID", email="")
        self.assertEqual(send_payment_receipt(str(booking.id)), "skipped:no-email")
        self.assertEqual(len(mail.outbox), 0)


class TaskRegistrationTests(TestCase):
    def test_tasks_are_registered_with_the_celery_app(self):
        from config.celery import app

        self.assertIn("apps.bookings.tasks.send_booking_confirmation", app.tasks)
        self.assertIn("apps.bookings.tasks.send_payment_receipt", app.tasks)