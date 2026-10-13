from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.bookings.models import Booking
from apps.payments.models import Payment
from apps.payments.views import VerifyRazorpayPaymentView


class VerifyRazorpayPaymentOrderMatchTests(TestCase):
    """F-21: a submitted razorpay_order_id must belong to the booking's own Payment."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            username='payer', email='payer@example.com', password='x'
        )
        self.booking = Booking.objects.create(
            user=self.user, status='PENDING', total_amount=Decimal('1000.00'),
            check_in=date(2026, 11, 1), check_out=date(2026, 11, 3),
        )
        self.payment = Payment.objects.create(
            booking=self.booking, stripe_session_id='order_real123',
            amount=Decimal('1000.00'), status='PENDING',
        )

    def _verify(self, order_id):
        request = self.factory.post('/api/payments/verify/', {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': 'pay_abc123',
            'razorpay_signature': 'sig_doesnt_matter_mocked',
            'booking_id': str(self.booking.id),
        }, format='json')
        force_authenticate(request, user=self.user)
        return VerifyRazorpayPaymentView.as_view()(request)

    @patch('apps.payments.views.RazorpayService.verify_payment', return_value=True)
    def test_mismatched_order_id_rejected_before_state_change(self, mock_verify):
        response = self._verify('order_fake999')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'PENDING')

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'PENDING')

    @patch('apps.payments.views.RazorpayService.verify_payment', return_value=True)
    def test_matching_order_id_succeeds(self, mock_verify):
        response = self._verify('order_real123')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'SUCCESS')

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'PAID')