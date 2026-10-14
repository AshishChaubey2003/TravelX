import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.bookings.models import Booking, BookingItem
from apps.locations.models import City
from apps.payments.models import Payment, WebhookEvent
from apps.payments.webhooks import RazorpayWebhookView
from apps.vehicles.models import Vehicle


class RazorpayRefundWebhookVehicleRestorationTests(TestCase):
    """
    F-19: a processed refund webhook must restore Vehicle.is_available, and a
    duplicate delivery of the same event must not restore it twice or error.

    Signature verification is mocked - no live Razorpay call is made.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            username='webhook_user', email='webhook_user@example.com', password='x'
        )
        self.city = City.objects.create(
            name='Test City', state='Test State', latitude='12.971600', longitude='77.594600',
        )
        self.vehicle = Vehicle.objects.create(
            city=self.city, name='Test Vehicle', vehicle_type='CAR',
            price_per_day=Decimal('800.00'), latitude='12.971600', longitude='77.594600',
            is_available=False,
        )
        self.booking = Booking.objects.create(
            user=self.user, status='PAID', total_amount=Decimal('1600.00'),
            check_in=date(2026, 11, 1), check_out=date(2026, 11, 3),
        )
        BookingItem.objects.create(
            booking=self.booking, item_type='VEHICLE', item_id=self.vehicle.id,
            item_name=self.vehicle.name, price_at_booking=Decimal('1600.00'), quantity=1,
        )
        self.payment = Payment.objects.create(
            booking=self.booking, stripe_payment_intent_id='pay_test123',
            stripe_session_id='order_test123', amount=Decimal('1600.00'), status='SUCCESS',
        )

    def _post_refund_webhook(self, event_id):
        payload = {
            'event': 'refund.processed',
            'created_at': 1234567890,
            'payload': {
                'refund': {
                    'entity': {
                        'id': 'rfnd_test123',
                        'payment_id': 'pay_test123',
                    }
                }
            },
        }
        request = self.factory.post(
            '/api/v1/payments/razorpay/webhook/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='test-signature',
            HTTP_X_RAZORPAY_EVENT_ID=event_id,
        )
        return RazorpayWebhookView.as_view()(request)

    @patch('apps.payments.webhooks.RazorpayService.verify_webhook_signature', return_value=True)
    def test_refund_processed_restores_vehicle_availability(self, mock_verify):
        response = self._post_refund_webhook(event_id='evt_refund_1')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.vehicle.refresh_from_db()
        self.assertTrue(self.vehicle.is_available)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'REFUNDED')

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'CANCELLED')

    @patch('apps.payments.webhooks.RazorpayService.verify_webhook_signature', return_value=True)
    def test_duplicate_refund_webhook_does_not_restore_twice_or_error(self, mock_verify):
        first = self._post_refund_webhook(event_id='evt_refund_2')
        self.assertEqual(first.status_code, status.HTTP_200_OK)

        self.vehicle.refresh_from_db()
        self.assertTrue(self.vehicle.is_available)

        second = self._post_refund_webhook(event_id='evt_refund_2')
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data['status'], 'duplicate')

        self.vehicle.refresh_from_db()
        self.assertTrue(self.vehicle.is_available)

        self.assertEqual(
            WebhookEvent.objects.filter(event_type='refund.processed').count(), 1
        )