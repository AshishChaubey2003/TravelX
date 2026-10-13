"""
Batch 1 regression tests: RefundView guard branches and gateway failure.
All assert CURRENT, correct behaviour and must pass as-is. The Razorpay refund
call is mocked; no live call is made.
"""
import uuid
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.bookings.models import Booking
from apps.payments.models import Payment

REFUND_URL = "/api/v1/payments/refund/"


class RefundViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ref_user", email="ref@example.com", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _booking(self, status="PAID"):
        return Booking.objects.create(
            user=self.user, status=status, total_amount=Decimal("1000.00"),
            check_in=date(2030, 1, 1), check_out=date(2030, 1, 3),
        )

    def _payment(self, booking, status="SUCCESS", intent="pay_1"):
        return Payment.objects.create(
            booking=booking, amount=Decimal("1000.00"), status=status,
            stripe_payment_intent_id=intent,
        )

    def test_refund_success_sets_refund_pending(self):
        booking = self._booking()
        payment = self._payment(booking)
        with mock.patch("apps.payments.views.RazorpayService.initiate_refund",
                        return_value={"id": "rfnd_1"}):
            resp = self.client.post(REFUND_URL, {"booking_id": str(booking.id)}, format="json")
        self.assertEqual(resp.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "REFUND_PENDING")
        self.assertEqual(payment.razorpay_refund_id, "rfnd_1")
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")

    def test_refund_already_refunded_is_rejected(self):
        booking = self._booking()
        self._payment(booking, status="REFUNDED")
        resp = self.client.post(REFUND_URL, {"booking_id": str(booking.id)}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_refund_in_progress_is_rejected(self):
        booking = self._booking()
        self._payment(booking, status="REFUND_PENDING")
        resp = self.client.post(REFUND_URL, {"booking_id": str(booking.id)}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_refund_non_success_payment_is_rejected(self):
        booking = self._booking()
        self._payment(booking, status="PENDING")
        resp = self.client.post(REFUND_URL, {"booking_id": str(booking.id)}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_refund_without_payment_reference_is_rejected(self):
        booking = self._booking()
        self._payment(booking, status="SUCCESS", intent=None)
        resp = self.client.post(REFUND_URL, {"booking_id": str(booking.id)}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_refund_unknown_booking_is_404(self):
        resp = self.client.post(REFUND_URL, {"booking_id": str(uuid.uuid4())}, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_refund_gateway_failure_keeps_payment_success(self):
        booking = self._booking()
        payment = self._payment(booking)
        with mock.patch("apps.payments.views.RazorpayService.initiate_refund",
                        side_effect=ValueError("Refund could not be initiated")):
            resp = self.client.post(REFUND_URL, {"booking_id": str(booking.id)}, format="json")
        self.assertEqual(resp.status_code, 400)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "SUCCESS")