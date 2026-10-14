import json
import logging
import time

from confluent_kafka import Consumer, KafkaError
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .schemas import EventValidationError, validate_event
from .topics import (
    TOPIC_BOOKING_CREATED,
    TOPIC_PAYMENT_SUCCESS,
    TOPIC_PAYMENT_FAILED,
    TOPIC_BOOKING_CANCELLED,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 5
MAX_BACKOFF_SECONDS = 30


def get_consumer(group_id: str):
    return Consumer({
        'bootstrap.servers': settings.KAFKA_BROKER,
        'group.id': group_id,
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False,
    })


def _max_attempts():
    """Attempts before an event is dead-lettered. Override with
    KAFKA_CONSUMER_MAX_ATTEMPTS in settings.py if needed."""
    return getattr(settings, 'KAFKA_CONSUMER_MAX_ATTEMPTS', DEFAULT_MAX_ATTEMPTS)


def parse_event(topic, raw_value):
    """
    Decode raw Kafka message bytes and validate them against the topic schema
    (G06). Raises EventValidationError for anything that can never become
    valid on redelivery: empty body, bad UTF-8, bad JSON, wrong shape,
    unsupported schema_version, missing/invalid fields.
    """
    if raw_value is None:
        raise EventValidationError('empty message body')
    try:
        payload = json.loads(raw_value.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as e:
        raise EventValidationError(f'unparseable message body: {e}')
    return validate_event(topic, payload)


def build_event_key(topic, payload, msg):
    """
    Identity used by the processed-events ledger (G07).

    Events carrying an event_id are identified by it, so a duplicate produced
    twice (e.g. a producer retry) is recognised even at a different offset.
    Older events without an event_id fall back to topic/partition/offset,
    which only recognises redelivery of that exact Kafka message.
    """
    event_id = payload.get('event_id')
    if event_id:
        return f'{topic}:event:{event_id}'
    return f'{topic}:kafka:{msg.partition()}:{msg.offset()}'


def dispatch_event(topic, payload):
    """
    Route one decoded event to its handler.

    Raises if the handler itself raises an unexpected failure. The caller
    (run_booking_consumer) then rewinds to this message and retries it, and
    dead-letters it after repeated failures (G10).

    A *known*, already-handled condition (the referenced booking_id doesn't
    exist, or the payload is missing/malformed) is NOT re-raised — each
    handler below logs and returns in that case, so the offset IS committed
    and the event is NOT retried. That is deliberate: an event that can
    never succeed (its booking_id will never start existing) would otherwise
    burn all its retry attempts for nothing.
    """
    if topic == TOPIC_BOOKING_CREATED:
        handle_booking_created(payload)
    elif topic == TOPIC_PAYMENT_SUCCESS:
        handle_payment_success(payload)
    elif topic == TOPIC_PAYMENT_FAILED:
        handle_payment_failed(payload)
    elif topic == TOPIC_BOOKING_CANCELLED:
        handle_booking_cancelled(payload)
    else:
        logger.warning(f'No handler registered for topic: {topic}')


def process_event_once(topic, payload, event_key):
    """
    Handle an event at most once per event_key (G07).

    The ledger row and the handler's own database changes happen in ONE
    transaction:
    - duplicate  -> the unique key rejects the ledger insert; the handler is
                    not run; returns False.
    - handler OK -> both the ledger row and the handler's changes commit;
                    returns True.
    - handler raises -> everything rolls back (including the ledger row) and
                    the exception propagates.

    Limits — the exactly-once boundary, stated precisely (F-008 review):
    - DATABASE effects ARE exactly-once per event_key: the ledger row and the
      handler's own writes commit or roll back together.
    - Celery task dispatch is NOT: handlers call .delay() inside this
      transaction, and a broker enqueue cannot be rolled back with it. There
      is deliberately NO transaction.on_commit here: on_commit would convert
      a crash between commit and callback into SILENT task loss (the event is
      recorded processed, so nothing retries). The current placement errs the
      other way — a commit failure after enqueue yields a retryable duplicate,
      which the task layer suppresses (EmailNotification's locked
      (booking, kind) ledger in apps/bookings/tasks.py, plus
      ReceiptNotYetVisible for the task-reads-before-commit race).
    - The one window neither layer closes: a worker dying after the SMTP
      server accepted a message but before the task's own commit can send one
      duplicate email (documented in apps/bookings/tasks.py).
    So: duplicate suppression with atomic database effects — not end-to-end
    exactly-once delivery, and task side effects are at-least-once.
    """
    from .models import ProcessedEvent

    with transaction.atomic():
        try:
            with transaction.atomic():
                ProcessedEvent.objects.create(event_key=event_key, topic=topic)
        except IntegrityError:
            logger.info(f'Duplicate event {event_key} already processed; skipping')
            return False
        dispatch_event(topic, payload)
    return True


def record_event_failure(topic, event_key, payload, msg, error, max_attempts):
    """
    Record one failed processing attempt (G10) in its own transaction, after
    the failed attempt's transaction has already rolled back.

    Returns (is_dead, attempts). is_dead is True once attempts reach
    max_attempts; the caller then commits past the event so it cannot block
    the partition forever.
    """
    from .models import FailedEvent

    with transaction.atomic():
        failed, _created = FailedEvent.objects.select_for_update().get_or_create(
            event_key=event_key,
            defaults={'topic': topic, 'payload': payload},
        )
        failed.topic = topic
        failed.payload = payload
        failed.partition = msg.partition()
        failed.offset = msg.offset()
        failed.attempts += 1
        failed.last_error = str(error)[:2000]
        if failed.attempts >= max_attempts:
            failed.status = FailedEvent.STATUS_DEAD
            failed.dead_at = timezone.now()
        else:
            failed.status = FailedEvent.STATUS_RETRYING
        failed.save()
    return failed.status == FailedEvent.STATUS_DEAD, failed.attempts


def _mark_resolved(event_key):
    """An event that was RETRYING and has now succeeded becomes RESOLVED."""
    from .models import FailedEvent

    try:
        FailedEvent.objects.filter(
            event_key=event_key, status=FailedEvent.STATUS_RETRYING
        ).update(status=FailedEvent.STATUS_RESOLVED)
    except Exception as e:
        logger.error(f'Could not mark failed event {event_key} resolved: {e}')


def _rewind(consumer, msg):
    """
    Seek back to the failed message so the next poll() returns it again.

    Without this a consumer never re-reads an uncommitted message in the same
    session, and committing any later message would commit past the failed
    one, silently losing it.
    """
    try:
        from confluent_kafka import TopicPartition
        consumer.seek(TopicPartition(msg.topic(), msg.partition(), msg.offset()))
    except Exception as e:
        logger.error(
            f'Could not rewind {msg.topic()} to offset {msg.offset()}: {e} — '
            f'the event will be re-read only after a consumer restart'
        )


def _commit(consumer, msg):
    """
    Synchronously commit the offset (G07). confluent-kafka commits
    asynchronously by default, which hides commit failures. A failed commit is
    logged but does not stop the consumer: the message is redelivered and the
    processed-events ledger makes that redelivery harmless.
    """
    try:
        consumer.commit(message=msg, asynchronous=False)
    except Exception as e:
        logger.error(
            f'Offset commit failed for {msg.topic()}: {e} — '
            f'the event will be redelivered and skipped as a duplicate'
        )


def run_booking_consumer():
    """
    Main consumer — subscribe to all topics
    Run as: python manage.py run_consumer
    """
    consumer = get_consumer('travelx-booking-group')
    consumer.subscribe([
        TOPIC_BOOKING_CREATED,
        TOPIC_PAYMENT_SUCCESS,
        TOPIC_PAYMENT_FAILED,
        TOPIC_BOOKING_CANCELLED,
    ])

    logger.info('Kafka consumer started — listening for events...')

    try:
        while True:
            msg = consumer.poll(timeout=1.0)

            if msg is None:
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                else:
                    logger.error(f'Consumer error: {msg.error()}')
                    continue

            topic = msg.topic()

            try:
                payload = parse_event(topic, msg.value())
            except EventValidationError as e:
                # An invalid event will never become valid on redelivery, so
                # log it and commit past it instead of looping on it forever
                # (or crashing the whole consumer process).
                logger.error(f'Skipping invalid event on {topic}: {e}')
                _commit(consumer, msg)
                continue

            event_key = build_event_key(topic, payload, msg)
            logger.info(f'Received event from {topic}: {payload}')

            try:
                process_event_once(topic, payload, event_key)
            except Exception as e:
                # G10: bounded retry. The failed attempt's transaction has
                # rolled back, so nothing was half-applied.
                max_attempts = _max_attempts()
                try:
                    is_dead, attempts = record_event_failure(
                        topic, event_key, payload, msg, repr(e), max_attempts
                    )
                except Exception as record_error:
                    logger.error(
                        f'Could not record failure for {event_key}: {record_error}'
                    )
                    is_dead, attempts = False, 1

                if is_dead:
                    logger.error(
                        f'Event {event_key} on {topic} dead-lettered after {attempts} '
                        f'attempts: {e}. Offset committed. Fix the cause, then run: '
                        f'python manage.py recovery replay-events --all'
                    )
                    _commit(consumer, msg)
                else:
                    logger.error(
                        f'Error processing event {topic}: {e} — '
                        f'attempt {attempts}/{max_attempts}, will retry'
                    )
                    _rewind(consumer, msg)
                    time.sleep(min(2 ** attempts, MAX_BACKOFF_SECONDS))
                continue

            # Reached for both newly processed and duplicate events.
            _mark_resolved(event_key)
            _commit(consumer, msg)

    except KeyboardInterrupt:
        logger.info('Consumer stopped by user')
    finally:
        consumer.close()


def run_inline(topic, outbox_event):
    """
    Demo-mode inline consumer: process an outbox event synchronously.

    Called via transaction.on_commit() after the producing transaction commits.
    Uses the same ProcessedEvent ledger as the Kafka consumer, so:
    - If this succeeds, a future Kafka delivery is a noop (deduplicated).
    - If this fails, the outbox row exists for eventual Kafka delivery or
      manual replay (manage.py recovery replay-events --all).

    Exceptions are logged and swallowed: the producing transaction has already
    committed, so the primary state (Payment/Booking) is safe. A failure here
    means the booking status transition is deferred — operationally equivalent
    to Kafka consumer lag in the full stack.
    """
    event_key = f'{topic}:event:{outbox_event.event_id}'
    payload = outbox_event.payload
    try:
        process_event_once(topic, payload, event_key)
    except Exception:
        logger.error(
            'Inline consumer failed for %s event_id=%s: '
            'booking transition deferred until replay or Kafka delivery',
            topic, outbox_event.event_id, exc_info=True,
        )


def handle_booking_created(payload):
    from apps.bookings.tasks import send_booking_confirmation
    booking_id = payload.get('booking_id')
    logger.info(f'Booking created event received: {booking_id}')
    if not booking_id:
        logger.error('booking.created event has no booking_id; confirmation email not queued')
        return
    # If the broker is down this raises and the event is retried (G10).
    send_booking_confirmation.delay(str(booking_id))


def handle_payment_success(payload):
    from django.core.exceptions import ValidationError
    from apps.bookings.models import Booking
    from apps.bookings.tasks import send_payment_receipt
    from .policy import can_transition
    booking_id = payload.get('booking_id')
    logger.info(f'Payment success: {booking_id}')
    try:
        booking = Booking.objects.get(id=booking_id)
    except (Booking.DoesNotExist, ValueError, TypeError, ValidationError):
        # Missing/invalid/unknown booking_id can never succeed on retry, so it
        # is logged and returned, not re-raised.
        logger.error(f'Payment success event for unknown/invalid booking_id={booking_id!r}')
        return
    # M16 race fix: the transition DECISION must be made on a row we hold.
    # Previously the status was read without a lock, so a cancellation (user
    # cancel, payment.failed event, or the expiry sweep) could commit
    # CANCELLED + release the inventory between our read and our write, and
    # this handler then blind-wrote PAID — a paid booking whose inventory was
    # already given back. Same locked shape as handle_payment_failed below:
    # re-read under select_for_update, gate on the CURRENT status, write in
    # the same transaction. (On SQLite the lock is a no-op; only PostgreSQL
    # proves the serialisation.)
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.status == 'PAID':
            # Duplicate/redelivered event: nothing to change. The receipt task
            # is idempotent (G03), so it is still queued below.
            logger.info(f'Booking {booking_id} is already PAID; status unchanged')
        elif can_transition(booking.status, 'PAID'):
            booking.status = 'PAID'
            booking.save(update_fields=['status'])
            logger.info(f'Booking {booking_id} marked PAID from payment.success event')
        else:
            # G11 / F-006 (DEFERRED): e.g. a CANCELLED booking is never marked
            # PAID by an event — a late capture lands on manual review, with
            # no automatic refund or inventory change invented here.
            logger.error(
                f'Payment success event for booking {booking_id} in status {booking.status}: '
                f'not marked PAID; needs manual review (possible refund)'
            )
            return
    send_payment_receipt.delay(str(booking.id))


def handle_payment_failed(payload):
    from django.core.exceptions import ValidationError
    from apps.bookings.models import Booking
    from apps.bookings.services import BookingService
    from .policy import can_transition
    booking_id = payload.get('booking_id')
    logger.info(f'Payment failed: {booking_id}')
    try:
        booking = Booking.objects.get(id=booking_id)
    except (Booking.DoesNotExist, ValueError, TypeError, ValidationError):
        logger.error(f'Payment failed event for unknown/invalid booking_id={booking_id!r}')
        return
    # Cancellation and the inventory release happen in ONE transaction, under a
    # row lock, and only on the transition INTO CANCELLED. A duplicate or
    # concurrent failure event therefore cannot release the same reservation
    # twice, and a PAID booking is never cancelled or released (G11).
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.status == 'CANCELLED':
            logger.info(f'Booking {booking_id} is already CANCELLED; status unchanged')
            return
        if not can_transition(booking.status, 'CANCELLED'):
            # G11: a PAID booking is never cancelled by a (late or duplicate) failure event.
            logger.warning(
                f'Payment failed event ignored for booking {booking_id}: '
                f'status is {booking.status}, which an event may not cancel'
            )
            return
        BookingService.release_inventory(booking)
        booking.status = 'CANCELLED'
        booking.save(update_fields=['status'])


def handle_booking_cancelled(payload):
    """
    No-op by design for now: cancellation already happens synchronously in
    apps/bookings/views.py (BookingCancelView) at the time of the API call.
    Logged only, so the topic is handled without crashing.
    """
    booking_id = payload.get('booking_id')
    logger.info(f'Booking cancelled event received: {booking_id}')