"""
DEMO_INLINE_CONSUMER tests — M18.

Verify that the inline consumer path (transaction.on_commit → run_inline →
process_event_once) correctly processes booking and payment events without
Kafka, preserving all existing idempotency, race-condition, and email-failure
guarantees.

These tests run on SQLite (the default test database). Row-lock serialisation
is NOT proven here — those guarantees were established in M16/M17 on
PostgreSQL and are unchanged by this feature.
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings

from apps.bookings.models import Booking, BookingItem
from apps.bookings.services import BookingService
from apps.bookings.tasks import send_booking_confirmation, send_payment_receipt
from apps.hotels.models import Hotel
from apps.kafka_events.consumers import run_inline, process_event_once
from apps.kafka_events.models import OutboxEvent, ProcessedEvent
from apps.kafka_events.topics import (
    TOPIC_BOOKING_CREATED,
    TOPIC_PAYMENT_FAILED,
    TOPIC_PAYMENT_SUCCESS,
)
from apps.locations.models import City
from apps.payments.models import Payment, WebhookEvent


# --- Helpers (reuse patterns from test_services.py / test_payment_success_race.py) ---

def _make_city(name="InlineCity"):
    return City.objects.create(
        name=name, state="Test State", latitude="12.971600", longitude="77.594600",
    )


def _make_user(username="inline_user"):
    return User.objects.create_user(
        username=username, email=f"{username}@example.com", password="x"
    )


def _make_hotel(city, **overrides):
    defaults = dict(
        city=city, name="Inline Hotel", description="test",
        price_per_night=Decimal("1000.00"), total_rooms=3, available_rooms=3,
        latitude="12.0", longitude="77.0", is_active=True,
    )
    defaults.update(overrides)
    return Hotel.objects.create(**defaults)


def _make_booking(user, hotel):
    """Create a real booking via BookingService so inventory is reserved."""
    return BookingService.create_booking(user, {
        "hotel_id": str(hotel.id),
        "check_in": "2026-12-01",
        "check_out": "2026-12-03",
    })


def _make_payment(booking, status='PENDING'):
    return Payment.objects.create(
        booking=booking,
        amount=booking.total_amount,
        status=status,
        stripe_session_id=f'order_{booking.id}',
        stripe_payment_intent_id=f'pay_{booking.id}',
    )


# ---------------------------------------------------------------------------
# 1. Inline payment.success: booking transitions PENDING → PAID
# ---------------------------------------------------------------------------
@override_settings(DEMO_INLINE_CONSUMER=True, CELERY_TASK_ALWAYS_EAGER=True,
                   CELERY_TASK_EAGER_PROPAGATES=False)
class InlinePaymentSuccessTests(TransactionTestCase):
    """TransactionTestCase so on_commit callbacks actually fire."""

    def setUp(self):
        self.city = _make_city()
        self.user = _make_user("pay_success")
        self.hotel = _make_hotel(self.city)
        self.booking = _make_booking(self.user, self.hotel)
        self.payment = _make_payment(self.booking)

    def test_inline_payment_success_marks_booking_paid(self):
        """The inline consumer processes payment.success and marks PAID."""
        outbox_event = OutboxEvent.objects.filter(
            topic=TOPIC_PAYMENT_SUCCESS
        ).first()
        # There should be no payment.success outbox event yet — it comes from
        # the webhook handler, not from create_booking. Create one manually
        # to test run_inline directly.
        from apps.kafka_events.outbox import enqueue_event
        outbox_event = enqueue_event(TOPIC_PAYMENT_SUCCESS, {
            'booking_id': str(self.booking.id),
            'user_id': str(self.user.id),
            'user_email': self.user.email,
            'amount': str(self.payment.amount),
            'stripe_session_id': self.payment.stripe_session_id,
        })

        with mock.patch.object(send_payment_receipt, 'delay') as mock_receipt:
            run_inline(TOPIC_PAYMENT_SUCCESS, outbox_event)

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'PAID')
        mock_receipt.assert_called_once_with(str(self.booking.id))
        # ProcessedEvent ledger records the event
        event_key = f'{TOPIC_PAYMENT_SUCCESS}:event:{outbox_event.event_id}'
        self.assertTrue(ProcessedEvent.objects.filter(event_key=event_key).exists())

    def test_inline_payment_success_duplicate_is_idempotent(self):
        """A second inline call with the same event_id is deduplicated."""
        from apps.kafka_events.outbox import enqueue_event
        outbox_event = enqueue_event(TOPIC_PAYMENT_SUCCESS, {
            'booking_id': str(self.booking.id),
            'user_id': str(self.user.id),
            'user_email': self.user.email,
            'amount': str(self.payment.amount),
            'stripe_session_id': self.payment.stripe_session_id,
        })

        with mock.patch.object(send_payment_receipt, 'delay'):
            run_inline(TOPIC_PAYMENT_SUCCESS, outbox_event)
            # Second call — same event
            run_inline(TOPIC_PAYMENT_SUCCESS, outbox_event)

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'PAID')
        event_key = f'{TOPIC_PAYMENT_SUCCESS}:event:{outbox_event.event_id}'
        self.assertEqual(ProcessedEvent.objects.filter(event_key=event_key).count(), 1)


# ---------------------------------------------------------------------------
# 2. Inline payment.failed: booking transitions PENDING → CANCELLED + inventory release
# ---------------------------------------------------------------------------
@override_settings(DEMO_INLINE_CONSUMER=True, CELERY_TASK_ALWAYS_EAGER=True,
                   CELERY_TASK_EAGER_PROPAGATES=False)
class InlinePaymentFailedTests(TransactionTestCase):

    def setUp(self):
        self.city = _make_city("FailCity")
        self.user = _make_user("pay_fail")
        self.hotel = _make_hotel(self.city, available_rooms=3, total_rooms=3)
        self.booking = _make_booking(self.user, self.hotel)

    def test_inline_payment_failed_cancels_and_releases_inventory(self):
        from apps.kafka_events.outbox import enqueue_event
        outbox_event = enqueue_event(TOPIC_PAYMENT_FAILED, {
            'booking_id': str(self.booking.id),
            'user_id': str(self.user.id),
            'user_email': self.user.email,
            'total_amount': str(self.booking.total_amount),
        })

        run_inline(TOPIC_PAYMENT_FAILED, outbox_event)

        self.booking.refresh_from_db()
        self.hotel.refresh_from_db()
        self.assertEqual(self.booking.status, 'CANCELLED')
        self.assertEqual(self.hotel.available_rooms, 3)  # inventory restored


# ---------------------------------------------------------------------------
# 3. Inline booking.created: confirmation email queued
# ---------------------------------------------------------------------------
@override_settings(DEMO_INLINE_CONSUMER=True, CELERY_TASK_ALWAYS_EAGER=True,
                   CELERY_TASK_EAGER_PROPAGATES=False)
class InlineBookingCreatedTests(TransactionTestCase):

    def setUp(self):
        self.city = _make_city("CreateCity")
        self.user = _make_user("book_create")
        self.hotel = _make_hotel(self.city)

    def test_inline_booking_created_queues_confirmation(self):
        # create_booking enqueues a booking.created outbox event. With
        # DEMO_INLINE_CONSUMER=True and TransactionTestCase (on_commit fires),
        # the inline consumer should process it.
        with mock.patch.object(send_booking_confirmation, 'delay') as mock_confirm:
            booking = _make_booking(self.user, self.hotel)

        # The on_commit callback should have called run_inline which calls
        # handle_booking_created which calls send_booking_confirmation.delay
        mock_confirm.assert_called_once_with(str(booking.id))

        # ProcessedEvent ledger should have the booking.created event
        outbox = OutboxEvent.objects.filter(topic=TOPIC_BOOKING_CREATED).first()
        self.assertIsNotNone(outbox)
        event_key = f'{TOPIC_BOOKING_CREATED}:event:{outbox.event_id}'
        self.assertTrue(ProcessedEvent.objects.filter(event_key=event_key).exists())


# ---------------------------------------------------------------------------
# 4. Cancelled booking not resurrected by inline payment.success
# ---------------------------------------------------------------------------
@override_settings(DEMO_INLINE_CONSUMER=True, CELERY_TASK_ALWAYS_EAGER=True,
                   CELERY_TASK_EAGER_PROPAGATES=False)
class InlineCancellationRaceTests(TransactionTestCase):
    """M16 race-condition guarantee preserved in inline mode."""

    def setUp(self):
        self.city = _make_city("RaceCity")
        self.user = _make_user("race_user")
        self.hotel = _make_hotel(self.city, available_rooms=3, total_rooms=3)
        self.booking = _make_booking(self.user, self.hotel)

    def test_cancelled_booking_not_resurrected_by_inline_success(self):
        # Cancel the booking (as BookingCancelView would)
        with transaction.atomic():
            locked = Booking.objects.select_for_update().get(pk=self.booking.pk)
            BookingService.release_inventory(locked)
            locked.status = 'CANCELLED'
            locked.save(update_fields=['status'])

        self.hotel.refresh_from_db()
        self.assertEqual(self.hotel.available_rooms, 3)

        # Now a late payment.success arrives
        from apps.kafka_events.outbox import enqueue_event
        outbox_event = enqueue_event(TOPIC_PAYMENT_SUCCESS, {
            'booking_id': str(self.booking.id),
            'user_id': str(self.user.id),
            'user_email': self.user.email,
            'amount': str(self.booking.total_amount),
            'stripe_session_id': 'order_late',
        })

        with mock.patch.object(send_payment_receipt, 'delay') as mock_receipt:
            run_inline(TOPIC_PAYMENT_SUCCESS, outbox_event)

        self.booking.refresh_from_db()
        self.hotel.refresh_from_db()
        # CANCELLED stays CANCELLED — the M16 can_transition gate rejects it
        self.assertEqual(self.booking.status, 'CANCELLED')
        self.assertEqual(self.hotel.available_rooms, 3)
        # No receipt for a non-PAID booking
        mock_receipt.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Inline consumer failure does not crash — exceptions swallowed
# ---------------------------------------------------------------------------
@override_settings(DEMO_INLINE_CONSUMER=True, CELERY_TASK_ALWAYS_EAGER=True,
                   CELERY_TASK_EAGER_PROPAGATES=False)
class InlineConsumerFailureTests(TransactionTestCase):

    def setUp(self):
        self.city = _make_city("FailSafe")
        self.user = _make_user("failsafe")
        self.hotel = _make_hotel(self.city)
        self.booking = _make_booking(self.user, self.hotel)

    def test_inline_failure_is_swallowed_and_logged(self):
        from apps.kafka_events.outbox import enqueue_event
        outbox_event = enqueue_event(TOPIC_PAYMENT_SUCCESS, {
            'booking_id': str(self.booking.id),
            'user_id': str(self.user.id),
            'user_email': self.user.email,
            'amount': str(self.booking.total_amount),
            'stripe_session_id': 'order_fail',
        })

        # Force process_event_once to raise
        with mock.patch(
            'apps.kafka_events.consumers.process_event_once',
            side_effect=RuntimeError('simulated DB failure'),
        ):
            # Should NOT raise — run_inline swallows the exception
            run_inline(TOPIC_PAYMENT_SUCCESS, outbox_event)

        # Booking stays PENDING (the inline call failed)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'PENDING')


# ---------------------------------------------------------------------------
# 6. Default mode: no inline processing (DEMO_INLINE_CONSUMER=False)
# ---------------------------------------------------------------------------
@override_settings(DEMO_INLINE_CONSUMER=False)
class DefaultModeNoInlineTests(TransactionTestCase):

    def setUp(self):
        self.city = _make_city("DefaultCity")
        self.user = _make_user("default_user")
        self.hotel = _make_hotel(self.city)

    def test_default_mode_does_not_call_inline(self):
        with mock.patch('apps.kafka_events.consumers.run_inline') as mock_inline:
            with mock.patch.object(send_booking_confirmation, 'delay'):
                _make_booking(self.user, self.hotel)

        # run_inline should NOT be called when flag is off
        mock_inline.assert_not_called()

        # But the outbox event should still exist (for the Kafka relay)
        self.assertTrue(OutboxEvent.objects.filter(topic=TOPIC_BOOKING_CREATED).exists())


# ---------------------------------------------------------------------------
# 7. Event key forward-compatibility with Kafka consumer
# ---------------------------------------------------------------------------
class EventKeyCompatibilityTests(TestCase):

    def test_inline_event_key_matches_kafka_consumer_key_format(self):
        """The inline consumer uses the same event_key format as the Kafka
        consumer's build_event_key(), so a message processed inline is
        recognised as a duplicate if later delivered by Kafka."""
        from apps.kafka_events.consumers import build_event_key
        import uuid

        event_id = str(uuid.uuid4())
        topic = TOPIC_PAYMENT_SUCCESS

        # Inline key format
        inline_key = f'{topic}:event:{event_id}'

        # Kafka consumer key format (when event_id is present in payload)
        payload = {'event_id': event_id, 'booking_id': str(uuid.uuid4())}

        class FakeMsg:
            def partition(self): return 0
            def offset(self): return 42

        kafka_key = build_event_key(topic, payload, FakeMsg())
        self.assertEqual(inline_key, kafka_key)


# ---------------------------------------------------------------------------
# 8. Celery eager mode: email task failure contained
# ---------------------------------------------------------------------------
@override_settings(DEMO_INLINE_CONSUMER=True, CELERY_TASK_ALWAYS_EAGER=True,
                   CELERY_TASK_EAGER_PROPAGATES=False)
class EagerCeleryEmailFailureTests(TransactionTestCase):
    """With CELERY_TASK_EAGER_PROPAGATES=False, a failing .delay() task
    does not propagate its exception to the caller."""

    def setUp(self):
        self.city = _make_city("EmailCity")
        self.user = _make_user("email_user")
        self.hotel = _make_hotel(self.city)
        self.booking = _make_booking(self.user, self.hotel)

    def test_email_failure_does_not_prevent_booking_paid(self):
        from apps.kafka_events.outbox import enqueue_event
        outbox_event = enqueue_event(TOPIC_PAYMENT_SUCCESS, {
            'booking_id': str(self.booking.id),
            'user_id': str(self.user.id),
            'user_email': self.user.email,
            'amount': str(self.booking.total_amount),
            'stripe_session_id': 'order_email_fail',
        })

        # Mock the email backend, not .delay(). With CELERY_TASK_ALWAYS_EAGER
        # and CELERY_TASK_EAGER_PROPAGATES=False, .delay() executes the task
        # synchronously and swallows any exception the task body raises.
        # Mocking .delay() directly would bypass Celery's eager machinery and
        # raise into handle_payment_success → process_event_once, rolling back
        # the PAID status change (since handle_payment_success's atomic block
        # is a savepoint inside process_event_once's outer atomic).
        with mock.patch(
            'django.core.mail.send_mail',
            side_effect=Exception('SMTP connection refused'),
        ):
            run_inline(TOPIC_PAYMENT_SUCCESS, outbox_event)

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'PAID')


# ---------------------------------------------------------------------------
# 9. Webhook integration test: end-to-end inline payment.success
# ---------------------------------------------------------------------------
@override_settings(DEMO_INLINE_CONSUMER=True, CELERY_TASK_ALWAYS_EAGER=True,
                   CELERY_TASK_EAGER_PROPAGATES=False)
class WebhookInlineIntegrationTests(TransactionTestCase):
    """End-to-end: webhook POST → _process → _handle_payment_captured →
    on_commit → run_inline → handle_payment_success → booking PAID."""

    def setUp(self):
        self.city = _make_city("WebhookCity")
        self.user = _make_user("webhook_user")
        self.hotel = _make_hotel(self.city)
        self.booking = _make_booking(self.user, self.hotel)
        self.payment = _make_payment(self.booking)

    def test_webhook_triggers_inline_consumer(self):
        import json
        import hmac
        import hashlib

        webhook_secret = 'test_webhook_secret'
        body_dict = {
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': self.payment.stripe_payment_intent_id,
                        'order_id': self.payment.stripe_session_id,
                        'amount': int(self.payment.amount * 100),
                        'currency': 'INR',
                        'status': 'captured',
                    }
                }
            }
        }
        body_bytes = json.dumps(body_dict).encode('utf-8')
        signature = hmac.new(
            webhook_secret.encode('utf-8'), body_bytes, hashlib.sha256,
        ).hexdigest()

        with self.settings(RAZORPAY_WEBHOOK_SECRET=webhook_secret):
            with mock.patch(
                'apps.payments.services.RazorpayService.verify_webhook_signature',
                return_value=True,
            ):
                with mock.patch.object(send_payment_receipt, 'delay') as mock_receipt:
                    from django.test import RequestFactory
                    from apps.payments.webhooks import RazorpayWebhookView

                    factory = RequestFactory()
                    request = factory.post(
                        '/api/v1/payments/razorpay/webhook/',
                        data=body_bytes,
                        content_type='application/json',
                        HTTP_X_RAZORPAY_SIGNATURE=signature,
                        HTTP_X_RAZORPAY_EVENT_ID='evt_test_inline',
                    )
                    response = RazorpayWebhookView.as_view()(request)

        self.assertEqual(response.status_code, 200)

        # Payment should be SUCCESS
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'SUCCESS')

        # Booking should be PAID (inline consumer processed it)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'PAID')

        # Receipt should have been queued
        mock_receipt.assert_called_once_with(str(self.booking.id))
