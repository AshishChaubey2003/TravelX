"""
Regression tests for the DEMO_INLINE_CONSUMER hook on the browser-submitted
payment verification path (VerifyRazorpayPaymentView).

In demo mode there is no Kafka relay, so the payment.success event the verify
view writes to the outbox must be driven through the SAME consumer handler
(run_inline -> process_event_once -> handle_payment_success) after the view's
transaction commits. The booking is already PAID by the view itself, so the
inline handler no-ops the status transition and only queues the receipt email,
while the ProcessedEvent ledger records the event (deduping any later Kafka
delivery).

on_commit callbacks only run on a real commit, so each test wraps the request
in captureOnCommitCallbacks(execute=True).
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.bookings.models import Booking
from apps.bookings.tasks import send_payment_receipt
from apps.kafka_events.models import OutboxEvent, ProcessedEvent
from apps.kafka_events.topics import TOPIC_PAYMENT_SUCCESS
from apps.payments.models import Payment
from apps.payments.views import VerifyRazorpayPaymentView


class _VerifyBase(TestCase):
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

    def _verify(self, order_id='order_real123'):
        request = self.factory.post('/api/payments/verify/', {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': 'pay_abc123',
            'razorpay_signature': 'sig_mocked',
            'booking_id': str(self.booking.id),
        }, format='json')
        force_authenticate(request, user=self.user)
        return VerifyRazorpayPaymentView.as_view()(request)


@override_settings(DEMO_INLINE_CONSUMER=True, CELERY_TASK_ALWAYS_EAGER=True,
                   CELERY_TASK_EAGER_PROPAGATES=False)
class VerifyInlineConsumerDemoModeTests(_VerifyBase):
    """DEMO_INLINE_CONSUMER=True: a successful verification drives the
    payment.success event through the inline consumer after commit."""

    @mock.patch('apps.payments.views.RazorpayService.verify_payment', return_value=True)
    def test_successful_verification_runs_inline_and_records_event(self, _mock_verify):
        with mock.patch.object(send_payment_receipt, 'delay') as mock_receipt:
            with self.captureOnCommitCallbacks(execute=True):
                response = self._verify()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # The view's own direct transition: payment SUCCESS, booking PAID.
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.payment.status, 'SUCCESS')
        self.assertEqual(self.booking.status, 'PAID')

        # The inline consumer ran: exactly one outbox event, and the
        # ProcessedEvent ledger recorded it under the matching event_key.
        outbox = OutboxEvent.objects.get(topic=TOPIC_PAYMENT_SUCCESS)
        event_key = f'{TOPIC_PAYMENT_SUCCESS}:event:{outbox.event_id}'
        self.assertTrue(ProcessedEvent.objects.filter(event_key=event_key).exists())

        # handle_payment_success reached its final step and queued the receipt
        # (booking was already PAID, so the status transition was a no-op).
        mock_receipt.assert_called_once_with(str(self.booking.id))

    @mock.patch('apps.payments.views.RazorpayService.verify_payment', return_value=True)
    def test_duplicate_verification_is_idempotent(self, _mock_verify):
        with mock.patch.object(send_payment_receipt, 'delay') as mock_receipt:
            with self.captureOnCommitCallbacks(execute=True):
                first = self._verify()
            # Second verification of the already-SUCCESS payment: no new event
            # is enqueued, so no second inline run.
            with self.captureOnCommitCallbacks(execute=True):
                second = self._verify()

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'PAID')

        # Exactly one event enqueued and one ledger row — not two.
        self.assertEqual(OutboxEvent.objects.filter(topic=TOPIC_PAYMENT_SUCCESS).count(), 1)
        self.assertEqual(ProcessedEvent.objects.filter(topic=TOPIC_PAYMENT_SUCCESS).count(), 1)

        # The receipt was queued once (first call only).
        mock_receipt.assert_called_once_with(str(self.booking.id))


@override_settings(DEMO_INLINE_CONSUMER=False)
class VerifyInlineConsumerDefaultModeTests(_VerifyBase):
    """Default mode (DEMO_INLINE_CONSUMER unset/False): verification still
    marks the booking PAID directly, but NO inline consumer runs — the event
    waits in the outbox for the Kafka relay, exactly as before M18."""

    @mock.patch('apps.payments.views.RazorpayService.verify_payment', return_value=True)
    def test_default_mode_does_not_run_inline(self, _mock_verify):
        with mock.patch.object(send_payment_receipt, 'delay') as mock_receipt:
            with self.captureOnCommitCallbacks(execute=True):
                response = self._verify()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # The view's own transition is unchanged.
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.payment.status, 'SUCCESS')
        self.assertEqual(self.booking.status, 'PAID')

        # The event is enqueued (for the relay) but NOT consumed inline.
        self.assertEqual(OutboxEvent.objects.filter(topic=TOPIC_PAYMENT_SUCCESS).count(), 1)
        self.assertFalse(ProcessedEvent.objects.filter(topic=TOPIC_PAYMENT_SUCCESS).exists())
        mock_receipt.assert_not_called()
