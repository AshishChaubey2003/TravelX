"""
Transactional outbox (checklist G08).

enqueue_event(): called inside the caller's database transaction. Validates
    and stamps the event (schema_version + event_id, see schemas.py) and
    writes an OutboxEvent row. If the surrounding transaction rolls back, the
    row disappears with it; if it commits, the event is guaranteed to exist
    and will be published.

publish_pending_events(): the relay. Locks a batch of due PENDING rows (with
    SKIP LOCKED so several relays can run side by side), produces them to
    Kafka, waits for delivery confirmation, then records the outcome.

Delivery guarantee: AT LEAST ONCE. If the relay dies, or a delivery is not
confirmed in time, the row stays PENDING and is sent again, which can create
a duplicate message. Duplicates carry the same event_id, which the consumer's
processed-events ledger (G07) recognises and skips.

Ordering: events for one booking are normally published in id order, but a
retry after a failure can publish a later event first. Do not rely on strict
ordering across retries.
"""
import json
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import OutboxEvent
from .producers import get_producer
from .schemas import prepare_event

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_ATTEMPTS = 10
FLUSH_TIMEOUT_SECONDS = 10


def enqueue_event(topic, payload):
    """
    Write an event to the outbox. Call this INSIDE the transaction that makes
    the change the event describes. Raises EventValidationError if the event
    does not match its schema: that is a programming error and must fail
    loudly instead of silently dropping the event.
    """
    event = prepare_event(topic, payload)
    return OutboxEvent.objects.create(
        event_id=event['event_id'],
        topic=topic,
        key=str(event.get('booking_id', 'unknown')),
        payload=event,
    )


def _backoff(attempts):
    """5s, 10s, 20s, ... capped at one hour."""
    return timedelta(seconds=min(5 * 2 ** attempts, 3600))


def publish_pending_events(batch_size=DEFAULT_BATCH_SIZE, max_attempts=DEFAULT_MAX_ATTEMPTS):
    """
    Publish one batch of due PENDING outbox rows. Returns a summary dict:
    {'published': n, 'failed': n, 'dead': n}.
    """
    summary = {'published': 0, 'failed': 0, 'dead': 0}
    producer = get_producer()

    with transaction.atomic():
        events = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(status=OutboxEvent.STATUS_PENDING, next_attempt_at__lte=timezone.now())
            .order_by('id')[:batch_size]
        )
        if not events:
            return summary

        results = {}  # pk -> (delivered_ok, error_message)

        for event in events:
            def on_delivery(err, msg, pk=event.pk):
                results[pk] = (err is None, '' if err is None else str(err))

            try:
                producer.produce(
                    topic=event.topic,
                    key=event.key.encode(),
                    value=json.dumps(event.payload).encode(),
                    callback=on_delivery,
                )
            except Exception as exc:
                results[event.pk] = (False, f'produce failed: {exc}')

        producer.flush(FLUSH_TIMEOUT_SECONDS)

        now = timezone.now()
        for event in events:
            delivered, error = results.get(
                event.pk, (False, 'delivery not confirmed before flush timeout')
            )
            event.attempts += 1

            if delivered:
                event.status = OutboxEvent.STATUS_PUBLISHED
                event.published_at = now
                event.last_error = ''
                summary['published'] += 1
            elif event.attempts >= max_attempts:
                event.status = OutboxEvent.STATUS_DEAD
                event.last_error = error
                summary['dead'] += 1
                logger.error(
                    'Outbox event %s (%s) is DEAD after %s attempts: %s',
                    event.event_id, event.topic, event.attempts, error,
                )
            else:
                event.next_attempt_at = now + _backoff(event.attempts)
                event.last_error = error
                summary['failed'] += 1
                logger.warning(
                    'Outbox event %s (%s) delivery failed (attempt %s): %s',
                    event.event_id, event.topic, event.attempts, error,
                )

            event.save(update_fields=[
                'status', 'attempts', 'last_error', 'next_attempt_at', 'published_at',
            ])

    return summary