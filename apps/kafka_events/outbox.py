"""
Transactional outbox (checklist G08) — F-008 lease design.

enqueue_event(): called inside the caller's database transaction. Validates
    and stamps the event (schema_version + event_id, see schemas.py) and
    writes an OutboxEvent row. If the surrounding transaction rolls back, the
    row disappears with it; if it commits, the event is guaranteed to exist
    and will be published. The event_id is stamped ONCE here and stored on the
    row; every retry re-serialises the stored payload, so duplicates always
    carry the same event_id.

publish_pending_events(): the relay, in three steps (F-008):

    1. RESERVE  — short transaction: lock a batch of due PENDING rows
                  (FOR UPDATE SKIP LOCKED so several relays can run side by
                  side) and move them to IN_FLIGHT under a fresh lease_id.
                  The locks are released when this transaction commits.
    2. PRODUCE  — OUTSIDE any database transaction: produce each payload and
                  flush. Delivery callbacks fire during flush and record a
                  per-row outcome. producers.get_producer sets
                  message.timeout.ms (5s) below FLUSH_TIMEOUT_SECONDS (10s),
                  so every produced message reaches a terminal callback
                  within the flush, barring process death.
    3. FINALIZE — per row, in its own short transaction: re-lock the row
                  WHERE pk AND lease_id = THIS pass's lease AND status =
                  IN_FLIGHT. Zero rows means this pass lost ownership (the
                  watchdog rescued the row, or another relay re-leased it):
                  write NOTHING — the row's new owner decides its fate, and
                  any already-delivered duplicate is absorbed by the
                  consumer's ProcessedEvent ledger. A missing callback result
                  is treated as NOT delivered ("delivery not confirmed"), so
                  uncertainty always lands on the retry side and is NEVER
                  converted into PUBLISHED.

rescue_stale_inflight_events(): the watchdog. Returns rows stuck IN_FLIGHT
    longer than OUTBOX_INFLIGHT_RESCUE_SECONDS (default 60 — comfortably
    above flush 10s + message.timeout 5s) to PENDING and CLEARS lease_id,
    which invalidates every outstanding finalizer for those rows. DORMANT:
    it has no schedule; run it manually (shell) or wire it to beat only
    after separate approval.

Delivery guarantee: AT-LEAST-ONCE. A row is marked PUBLISHED only on a
positive broker ack observed by this pass's own callback. Every ambiguous
outcome — crash between flush and finalize, flush timeout, lost lease —
re-queues the row, which can deliver the same message twice. Duplicates
carry the same event_id and are collapsed to exactly-once DATABASE effects
by the consumer ledger (G07). This is not end-to-end exactly-once: see
consumers.process_event_once for what the ledger does and does not cover.

Ordering: events for one booking are normally published in id order, but a
retry after a failure can publish a later event first. Do not rely on strict
ordering across retries.
"""
import json
import logging
import uuid
from datetime import timedelta

from django.conf import settings
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


def _rescue_cutoff_seconds():
    return getattr(settings, 'OUTBOX_INFLIGHT_RESCUE_SECONDS', 60)


def publish_pending_events(batch_size=DEFAULT_BATCH_SIZE, max_attempts=DEFAULT_MAX_ATTEMPTS):
    """
    Publish one batch of due PENDING outbox rows (Reserve → Produce →
    Finalize; see the module docstring). Returns a summary dict:
    {'published': n, 'failed': n, 'dead': n}.
    """
    summary = {'published': 0, 'failed': 0, 'dead': 0}
    producer = get_producer()
    lease = uuid.uuid4()

    # --- Step 1: RESERVE under a fresh lease (short transaction). ---
    with transaction.atomic():
        events = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(status=OutboxEvent.STATUS_PENDING, next_attempt_at__lte=timezone.now())
            .order_by('id')[:batch_size]
        )
        if not events:
            return summary
        OutboxEvent.objects.filter(pk__in=[e.pk for e in events]).update(
            status=OutboxEvent.STATUS_IN_FLIGHT,
            lease_id=lease,
            inflight_at=timezone.now(),
        )

    # --- Step 2: PRODUCE outside any transaction (no row locks held). ---
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

    # --- Step 3: FINALIZE, one short transaction per row, lease-scoped. ---
    now = timezone.now()
    for event in events:
        delivered, error = results.get(
            event.pk, (False, 'delivery not confirmed before flush timeout')
        )
        with transaction.atomic():
            locked = (
                OutboxEvent.objects.select_for_update()
                .filter(pk=event.pk,
                        lease_id=lease,
                        status=OutboxEvent.STATUS_IN_FLIGHT)
                .first()
            )
            if locked is None:
                # This pass lost ownership of the row (watchdog rescue, or a
                # re-reservation by another relay). Write NOTHING: the new
                # owner decides the row's fate, and a delivered duplicate is
                # absorbed by the consumer's event_id-keyed ledger.
                logger.warning(
                    'Outbox event %s: lease %s lost before finalize; '
                    'leaving the row to its new owner', event.event_id, lease,
                )
                continue

            locked.attempts += 1
            locked.lease_id = None
            locked.inflight_at = None

            if delivered:
                locked.status = OutboxEvent.STATUS_PUBLISHED
                locked.published_at = now
                locked.last_error = ''
                summary['published'] += 1
            elif locked.attempts >= max_attempts:
                locked.status = OutboxEvent.STATUS_DEAD
                locked.last_error = error
                summary['dead'] += 1
                logger.error(
                    'Outbox event %s (%s) is DEAD after %s attempts: %s',
                    locked.event_id, locked.topic, locked.attempts, error,
                )
            else:
                locked.status = OutboxEvent.STATUS_PENDING
                locked.next_attempt_at = now + _backoff(locked.attempts)
                locked.last_error = error
                summary['failed'] += 1
                logger.warning(
                    'Outbox event %s (%s) delivery failed (attempt %s): %s',
                    locked.event_id, locked.topic, locked.attempts, error,
                )

            locked.save(update_fields=[
                'status', 'attempts', 'last_error', 'next_attempt_at',
                'published_at', 'lease_id', 'inflight_at',
            ])

    return summary


def rescue_stale_inflight_events(rescue_seconds=None):
    """
    Watchdog (F-008; DORMANT — no schedule): return rows stuck IN_FLIGHT
    longer than OUTBOX_INFLIGHT_RESCUE_SECONDS to PENDING, due immediately.

    Clearing lease_id is the point: it invalidates every outstanding
    finalizer for the row, including one in a crashed-but-still-running pass
    blocked on a slow connection. The rescued row may ALREADY have been
    delivered (crash after flush, before finalize) — republishing it is the
    at-least-once trade; the consumer ledger drops the duplicate.

    Returns the number of rows rescued.
    """
    if rescue_seconds is None:
        rescue_seconds = _rescue_cutoff_seconds()
    cutoff = timezone.now() - timedelta(seconds=rescue_seconds)

    with transaction.atomic():
        pks = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(status=OutboxEvent.STATUS_IN_FLIGHT, inflight_at__lt=cutoff)
            .values_list('pk', flat=True)
        )
        if not pks:
            return 0
        rescued = OutboxEvent.objects.filter(pk__in=pks).update(
            status=OutboxEvent.STATUS_PENDING,
            lease_id=None,
            inflight_at=None,
            next_attempt_at=timezone.now(),
        )
    logger.warning('Outbox watchdog rescued %s stale IN_FLIGHT row(s)', rescued)
    return rescued
