"""
Razorpay server-side webhook (inbound).

Security
--------
Every request must carry a valid X-Razorpay-Signature: HMAC-SHA256 over the
exact raw body, keyed with RAZORPAY_WEBHOOK_SECRET. A missing, malformed or
invalid signature changes NO payment, booking, inventory or outbox state.

Idempotency — two independent guards
------------------------------------
1. WebhookEvent.event_key is unique and inserted in the SAME transaction as
   the handler's changes, so a duplicate delivery cannot apply them twice.
2. Every handler also gates on the payment's own state transition, so even
   where event identity is weak the transition cannot be applied twice. This
   is what prevents double inventory restoration on a repeated refund.

Reliability
-----------
Payment state and the outbox event are written in ONE transaction (G08), so
an outbox failure rolls the state change back. Kafka is never contacted here;
the existing relay delivers the event.

Booking status transitions for payments are NOT performed here. The outbox
event reaches the existing consumer handlers, which own them under the G11
policy. Refunds are the exception: they have no Kafka topic, so a confirmed
refund is applied here, atomically.
"""
import json
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.adventures.models import Adventure
from apps.bookings.models import Booking
from apps.core.flow_health import record_flow
from apps.hotels.models import Hotel
from apps.vehicles.models import Vehicle
from apps.kafka_events.outbox import enqueue_event
from apps.kafka_events.policy import can_refund_transition
from apps.kafka_events.topics import TOPIC_PAYMENT_FAILED, TOPIC_PAYMENT_SUCCESS

from .models import Payment, WebhookEvent
from .services import RazorpayService

logger = logging.getLogger(__name__)

EVENT_PAYMENT_CAPTURED = 'payment.captured'
EVENT_PAYMENT_FAILED = 'payment.failed'
EVENT_REFUND_PROCESSED = 'refund.processed'
EVENT_REFUND_FAILED = 'refund.failed'

HANDLED_EVENT_TYPES = frozenset({
    EVENT_PAYMENT_CAPTURED,
    EVENT_PAYMENT_FAILED,
    EVENT_REFUND_PROCESSED,
    EVENT_REFUND_FAILED,
})

# Kept out of Payment.raw_webhook: card, contact and customer details are not
# needed to reconcile a payment or argue a dispute.
_SENSITIVE_ENTITY_FIELDS = frozenset({
    'card', 'card_id', 'email', 'contact', 'vpa', 'bank', 'wallet',
    'customer_id', 'token_id', 'notes', 'acquirer_data', 'upi',
})


class RazorpayWebhookView(APIView):
    """
    POST /api/v1/payments/razorpay/webhook/

    200 processed / duplicate / ignored-unknown-type
    400 malformed body or unusable entity (a retry cannot fix it)
    401 missing or invalid signature
    500 transient failure — everything rolled back, Razorpay should retry
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        # Read the raw body FIRST. Touching request.data makes request.body
        # unavailable, and the signature covers these exact bytes.
        raw_body = request.body
        signature = request.META.get('HTTP_X_RAZORPAY_SIGNATURE', '')

        if not RazorpayService.verify_webhook_signature(raw_body, signature):
            logger.warning('Razorpay webhook rejected: signature missing or invalid')
            record_flow('payment_webhook', 'rejected', reason='invalid_signature')
            return Response({'error': 'invalid signature'},
                            status=status.HTTP_401_UNAUTHORIZED)

        try:
            payload = json.loads(raw_body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            record_flow('payment_webhook', 'rejected', reason='unparseable_body')
            return Response({'error': 'invalid payload'},
                            status=status.HTTP_400_BAD_REQUEST)

        if not isinstance(payload, dict):
            record_flow('payment_webhook', 'rejected', reason='payload_not_object')
            return Response({'error': 'invalid payload'},
                            status=status.HTTP_400_BAD_REQUEST)

        event_type = payload.get('event')
        if not isinstance(event_type, str) or not event_type:
            record_flow('payment_webhook', 'rejected', reason='missing_event_type')
            return Response({'error': 'invalid payload'},
                            status=status.HTTP_400_BAD_REQUEST)

        entity = _extract_entity(payload, event_type)
        entity_id = (entity or {}).get('id') or ''
        event_key = _build_event_key(request, event_type, entity_id)

        logger.info('Razorpay webhook received: event=%s entity_id=%s',
                    event_type, entity_id)

        if event_type not in HANDLED_EVENT_TYPES:
            # 200 so Razorpay stops retrying an event we will never act on.
            _record_ignored(event_key, event_type, entity_id, 'event type not handled')
            record_flow('payment_webhook', 'success', reason='ignored_event_type')
            return Response({'status': 'ignored'}, status=status.HTTP_200_OK)

        if entity is None or not entity_id:
            _record_ignored(event_key, event_type, entity_id, 'no usable entity in payload')
            record_flow('payment_webhook', 'rejected', reason='missing_entity')
            return Response({'error': 'invalid payload'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            outcome = _process(event_key, event_type, entity, payload)
        except Exception as exc:
            # Transient. The transaction rolled back, ledger row included, so
            # the event is NOT recorded processed. 500 asks Razorpay to retry.
            logger.error('Razorpay webhook %s failed: %s',
                         event_key, type(exc).__name__, exc_info=True)
            record_flow('payment_webhook', 'failure',
                        reason=type(exc).__name__, exc_info=True)
            return Response({'error': 'processing failed'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if outcome == 'processed':
            record_flow('payment_webhook', 'success', reason=event_type)
            return Response({'status': 'ok'}, status=status.HTTP_200_OK)

        if outcome == 'duplicate':
            logger.info('Razorpay webhook %s is a duplicate; nothing applied', event_key)
            record_flow('payment_webhook', 'success', reason='duplicate')
            return Response({'status': 'duplicate'}, status=status.HTTP_200_OK)

        # Deliberately not acted on. The reason lives in the log and the
        # ledger, not in the response body.
        logger.info('Razorpay webhook %s not acted on: %s', event_key, outcome)
        record_flow('payment_webhook', 'success', reason='ignored')
        return Response({'status': 'ignored'}, status=status.HTTP_200_OK)


def _process(event_key, event_type, entity, payload):
    """
    Apply one webhook event. The ledger row and every database change happen
    in ONE transaction, exactly like the consumer's process_event_once (G07):

      duplicate      -> the unique event_key rejects the insert; nothing applied
      handler OK     -> ledger row and changes commit together
      handler raises -> everything rolls back, ledger row included
    """
    with transaction.atomic():
        try:
            with transaction.atomic():
                ledger = WebhookEvent.objects.create(
                    event_key=event_key,
                    event_type=event_type,
                    razorpay_payment_id=_payment_reference(event_type, entity),
                )
        except IntegrityError:
            return 'duplicate'

        if event_type == EVENT_PAYMENT_CAPTURED:
            outcome = _handle_payment_captured(entity, payload)
        elif event_type == EVENT_PAYMENT_FAILED:
            outcome = _handle_payment_failed(entity, payload)
        elif event_type == EVENT_REFUND_PROCESSED:
            outcome = _handle_refund_processed(entity, payload)
        else:
            outcome = _handle_refund_failed(entity, payload)

        if outcome != 'processed':
            ledger.status = WebhookEvent.STATUS_IGNORED
            ledger.note = outcome[:500]
            ledger.save(update_fields=['status', 'note'])

    return outcome


def _handle_payment_captured(entity, payload):
    payment = _locked_payment_for_payment_event(entity)
    if payment is None:
        return 'no matching payment for this order/payment id'
    if payment.status == 'SUCCESS':
        return 'payment already captured'
    if payment.status in ('REFUND_PENDING', 'REFUNDED'):
        logger.error('payment.captured for payment %s in status %s; needs manual review',
                     payment.pk, payment.status)
        return 'payment already refunded or refunding'

    booking = payment.booking
    payment.status = 'SUCCESS'
    payment.stripe_payment_intent_id = entity.get('id') or payment.stripe_payment_intent_id
    payment.webhook_received_at = timezone.now()
    payment.raw_webhook = _safe_webhook_record(payload, entity)
    payment.save(update_fields=[
        'status', 'stripe_payment_intent_id', 'webhook_received_at', 'raw_webhook',
    ])

    # G08: same transaction as the state change above. If this raises, the
    # payment transition rolls back rather than committing without its event.
    outbox_event = enqueue_event(TOPIC_PAYMENT_SUCCESS, {
        'booking_id': str(booking.id),
        'user_id': str(booking.user.id),
        'user_email': booking.user.email,
        'amount': str(payment.amount),
        'stripe_session_id': payment.stripe_session_id,
    })

    # DEMO_INLINE_CONSUMER: after the outer _process() transaction commits,
    # process the payment.success event inline (marks booking PAID, sends
    # receipt via eager Celery). on_commit fires only on the outermost atomic
    # — i.e. the _process() block — so Payment + outbox row are committed.
    if getattr(settings, 'DEMO_INLINE_CONSUMER', False):
        from apps.kafka_events.consumers import run_inline
        _evt = outbox_event
        transaction.on_commit(lambda: run_inline(TOPIC_PAYMENT_SUCCESS, _evt))

    return 'processed'


def _handle_payment_failed(entity, payload):
    payment = _locked_payment_for_payment_event(entity)
    if payment is None:
        return 'no matching payment for this order/payment id'
    if payment.status == 'SUCCESS':
        # A late or duplicate failure must never undo a captured payment.
        logger.warning('payment.failed ignored for payment %s: already SUCCESS', payment.pk)
        return 'payment already captured; failure ignored'
    if payment.status in ('REFUND_PENDING', 'REFUNDED'):
        return 'payment already refunded or refunding'
    if payment.status == 'FAILED':
        return 'payment already failed'

    booking = payment.booking
    payment.status = 'FAILED'
    payment.webhook_received_at = timezone.now()
    payment.raw_webhook = _safe_webhook_record(payload, entity)
    payment.save(update_fields=['status', 'webhook_received_at', 'raw_webhook'])

    outbox_event = enqueue_event(TOPIC_PAYMENT_FAILED, {
        'booking_id': str(booking.id),
        'user_id': str(booking.user.id),
        'user_email': booking.user.email,
        'total_amount': str(booking.total_amount),
    })

    # DEMO_INLINE_CONSUMER: inline payment.failed → cancels booking + releases
    # inventory, same guarantees as the Kafka consumer path.
    if getattr(settings, 'DEMO_INLINE_CONSUMER', False):
        from apps.kafka_events.consumers import run_inline
        _evt = outbox_event
        transaction.on_commit(lambda: run_inline(TOPIC_PAYMENT_FAILED, _evt))

    return 'processed'


def _handle_refund_processed(entity, payload):
    payment_id = entity.get('payment_id')
    if not payment_id:
        return 'refund entity has no payment_id'

    payment = _locked_payment_by_payment_id(payment_id)
    if payment is None:
        return 'no matching payment for this refund'
    if payment.status == 'REFUNDED':
        # First guard against restoring inventory twice.
        return 'refund already completed'
    if payment.status not in ('SUCCESS', 'REFUND_PENDING'):
        logger.error('refund.processed for payment %s in status %s; needs manual review',
                     payment.pk, payment.status)
        return 'payment not in a refundable state'

    booking = Booking.objects.select_for_update().get(pk=payment.booking_id)

    payment.status = 'REFUNDED'
    payment.razorpay_refund_id = entity.get('id') or payment.razorpay_refund_id
    payment.webhook_received_at = timezone.now()
    payment.raw_webhook = _safe_webhook_record(payload, entity)
    payment.save(update_fields=[
        'status', 'razorpay_refund_id', 'webhook_received_at', 'raw_webhook',
    ])

    if booking.status == 'CANCELLED':
        # Second guard: inventory was already restored for this booking.
        return 'processed'

    if not can_refund_transition(booking.status, 'CANCELLED'):
        logger.error(
            'Refund completed for booking %s but its status is %s; inventory '
            'not restored, needs manual review', booking.pk, booking.status,
        )
        return 'processed'

    _restore_inventory(booking)
    booking.status = 'CANCELLED'
    booking.save(update_fields=['status'])
    return 'processed'


def _handle_refund_failed(entity, payload):
    payment_id = entity.get('payment_id')
    if not payment_id:
        return 'refund entity has no payment_id'

    payment = _locked_payment_by_payment_id(payment_id)
    if payment is None:
        return 'no matching payment for this refund'
    if payment.status == 'REFUNDED':
        logger.error('refund.failed for payment %s already marked REFUNDED; '
                     'needs manual review', payment.pk)
        return 'payment already marked refunded'
    if payment.status != 'REFUND_PENDING':
        return 'no refund in progress for this payment'

    payment.status = 'SUCCESS'
    payment.webhook_received_at = timezone.now()
    payment.raw_webhook = _safe_webhook_record(payload, entity)
    payment.save(update_fields=['status', 'webhook_received_at', 'raw_webhook'])
    logger.warning('Refund failed for payment %s; payment restored to SUCCESS', payment.pk)
    return 'processed'


def _restore_inventory(booking):
    """
    Identical rules to BookingCancelView: restores Hotel and Adventure
    inventory, and Vehicle availability, using the same item_type dispatch.
    """
    for item in booking.items.all():
        if item.item_type == 'HOTEL':
            Hotel.objects.filter(id=item.item_id).update(
                available_rooms=F('available_rooms') + item.quantity
            )
        elif item.item_type == 'ADVENTURE':
            Adventure.objects.filter(id=item.item_id).update(
                current_bookings=F('current_bookings') - item.quantity
            )
        elif item.item_type == 'VEHICLE':
            Vehicle.objects.filter(id=item.item_id).update(
                is_available=True
            )


def _locked_payment_by_payment_id(payment_id):
    return Payment.objects.select_for_update().filter(
        stripe_payment_intent_id=payment_id
    ).first()


def _locked_payment_for_payment_event(entity):
    """
    A captured payment may not have its payment id recorded yet — the webhook
    can beat the browser's verify call — so fall back to the order id, which
    create_order always stores in stripe_session_id.
    """
    payment = None
    payment_id = entity.get('id')
    order_id = entity.get('order_id')
    if payment_id:
        payment = Payment.objects.select_for_update().filter(
            stripe_payment_intent_id=payment_id
        ).first()
    if payment is None and order_id:
        payment = Payment.objects.select_for_update().filter(
            stripe_session_id=order_id
        ).first()
    return payment


def _extract_entity(payload, event_type):
    container = payload.get('payload')
    if not isinstance(container, dict):
        return None
    section = container.get('refund' if event_type.startswith('refund.') else 'payment')
    if not isinstance(section, dict):
        return None
    entity = section.get('entity')
    return entity if isinstance(entity, dict) else None


def _payment_reference(event_type, entity):
    if event_type.startswith('refund.'):
        return str(entity.get('payment_id') or '')[:200]
    return str(entity.get('id') or '')[:200]


def _build_event_key(request, event_type, entity_id):
    """
    Prefer Razorpay's own event id, which recognises a duplicate delivery even
    of a re-sent event.

    LIMITATION: the fallback cannot distinguish a genuinely new event from a
    duplicate when two same-type events legitimately exist for one entity.
    The per-handler state-transition guards are what make that case safe.
    """
    event_id = request.META.get('HTTP_X_RAZORPAY_EVENT_ID', '')
    if event_id:
        return f'razorpay:event:{event_id}'[:255]
    return f'razorpay:{event_type}:{entity_id}'[:255]


def _safe_webhook_record(payload, entity):
    """Identifiers, amounts and status only — see _SENSITIVE_ENTITY_FIELDS."""
    return {
        'event': payload.get('event'),
        'created_at': payload.get('created_at'),
        'entity': {k: v for k, v in entity.items()
                   if k not in _SENSITIVE_ENTITY_FIELDS},
    }


def _record_ignored(event_key, event_type, entity_id, note):
    """Record a deliberately unhandled event so retries stop. Never raises."""
    try:
        WebhookEvent.objects.get_or_create(
            event_key=event_key,
            defaults={
                'event_type': event_type,
                'status': WebhookEvent.STATUS_IGNORED,
                'razorpay_payment_id': str(entity_id or '')[:200],
                'note': note[:500],
            },
        )
    except Exception as exc:
        logger.error('Could not record ignored webhook %s: %s',
                     event_key, type(exc).__name__)