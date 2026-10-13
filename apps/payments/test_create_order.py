"""
Batch 1 regression tests: Razorpay order creation.

- CreateOrderTests asserts current, correct behaviour and passes.
- RepeatCreateOrderKnownBugR1Tests encodes the post-fix invariant and FAILS
  against the current code (normal regression test, NOT expectedFailure).
  R1: a second create_order for the same booking leaves Payment.stripe_session_id
  on the first order while booking.stripe_session_id is overwritten with the
  second, so they diverge. Any reasonable fix keeps them in sync.
The Razorpay client is mocked; no live call is made.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from apps.bookings.models import Booking
from apps.payments.models import Payment
from apps.payments.services import RazorpayService


def _booking(user):
    return Booking.objects.create(
        user=user, status="PENDING", total_amount=Decimal("1000.00"),
        check_in=date(2030, 1, 1), check_out=date(2030, 1, 3),
    )


class CreateOrderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ord_user", email="ord@example.com", password="x")

    def test_create_order_records_payment_and_session_id(self):
        booking = _booking(self.user)
        order = {"id": "order_A", "amount": 100000, "currency": "INR"}
        with mock.patch("apps.payments.services.razorpay_client") as client:
            client.order.create.return_value = order
            result = RazorpayService.create_order(booking)
        self.assertEqual(result["id"], "order_A")
        payment = Payment.objects.get(booking=booking)
        self.assertEqual(payment.stripe_session_id, "order_A")
        booking.refresh_from_db()
        self.assertEqual(booking.stripe_session_id, "order_A")


class RepeatCreateOrderKnownBugR1Tests(TestCase):
    """KNOWN BUG R1 - EXPECTED TO FAIL until the fix lands."""

    def setUp(self):
        self.user = User.objects.create_user(username="ord_user2", email="ord2@example.com", password="x")

    def test_repeat_create_order_keeps_payment_and_booking_in_sync(self):
        booking = _booking(self.user)
        with mock.patch("apps.payments.services.razorpay_client") as client:
            client.order.create.side_effect = [
                {"id": "order_A", "amount": 100000, "currency": "INR"},
                {"id": "order_B", "amount": 100000, "currency": "INR"},
            ]
            RazorpayService.create_order(booking)
            RazorpayService.create_order(booking)
        payment = Payment.objects.get(booking=booking)
        booking.refresh_from_db()
        self.assertEqual(payment.stripe_session_id, booking.stripe_session_id)