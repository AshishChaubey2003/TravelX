"""
Event producers for TravelX.

POLICY — read this before adding any caller:
  Every event this project publishes to Kafka MUST go through the
  transactional outbox (apps/kafka_events/outbox.py::enqueue_event), inside
  the same database transaction as the state change the event describes.
  That is the G08 guarantee: no committed state without its event, no
  published event without its state.

This module keeps `publish_booking_created` because it already enforces the
outbox internally and is a stable public name used by `apps.bookings.services`
and existing tests. The other three helpers (`publish_payment_success`,
`publish_payment_failed`, `publish_booking_cancelled`) and the underlying
`publish_event` previously called Kafka directly, swallowed delivery errors,
and did NOT participate in any transaction — exactly the F-007 event-loss
pattern documented in docs/audit/FINDINGS.md. Grep confirms they have zero
production callers today; every real caller (webhooks, verify view) already
uses enqueue_event directly.

To prevent a future caller from accidentally bypassing the outbox, those
names now raise RuntimeError with a pointer to the correct API. This is a
loud failure, not a silent drop: a stray call surfaces as a 500 in testing
instead of a lost event in production.

If a legitimate reason to call Kafka directly ever arises (an operational
tool, a debug command), build it from `apps.kafka_events.outbox.get_producer`
inside its own module and route it through the outbox too — never resurrect
the direct helpers here.
"""
import logging

from confluent_kafka import Producer
from django.conf import settings

from .topics import TOPIC_BOOKING_CREATED

logger = logging.getLogger(__name__)

_DEPRECATION_MSG = (
    "Direct publish bypasses the transactional outbox and risks event loss "
    "(F-007). Use apps.kafka_events.outbox.enqueue_event(topic, payload) "
    "inside the same transaction as the state change. See the module "
    "docstring and docs/audit/FINDINGS.md F-007."
)

# The Kafka producer handle. Kept because `apps.kafka_events.outbox` imports
# it and uses it via the relay: produce + flush under the row-lock release
# pattern (see outbox.py). Keep this a module-level singleton so the TCP
# connection is reused across batches.
_producer = None


def get_producer():
    """Return the shared Kafka producer. Lazy to avoid connecting on import."""
    global _producer
    if _producer is None:
        _producer = Producer({
            'bootstrap.servers': settings.KAFKA_BROKER,
            'socket.timeout.ms': 5000,
            'message.timeout.ms': 5000,
        })
    return _producer


def delivery_report(err, msg):
    """Callback passed by the outbox relay to producer.produce()."""
    if err:
        logger.error('Kafka delivery failed: %s', err)
    else:
        logger.info('Event delivered to %s [%s]', msg.topic(), msg.partition())


def publish_event(topic, payload):  # noqa: ARG001 — names kept for signature compatibility
    raise RuntimeError(f"publish_event is removed: {_DEPRECATION_MSG}")


def publish_payment_success(booking, payment):  # noqa: ARG001
    raise RuntimeError(f"publish_payment_success is removed: {_DEPRECATION_MSG}")


def publish_payment_failed(booking):  # noqa: ARG001
    raise RuntimeError(f"publish_payment_failed is removed: {_DEPRECATION_MSG}")


def publish_booking_cancelled(booking):  # noqa: ARG001
    raise RuntimeError(f"publish_booking_cancelled is removed: {_DEPRECATION_MSG}")


# The remaining helper. This one is correct (writes to the outbox inside the
# caller's transaction) and has real callers (BookingService.create_booking,
# apps/kafka_events/test_outbox.py, apps/kafka_events/test_resilience.py).
# Do NOT remove or rename without updating those callers.
def publish_booking_created(booking):
    """
    G08: does NOT talk to Kafka. Writes the booking.created event to the
    transactional outbox, so it must be called inside the same database
    transaction that creates the booking. The relay
    (manage.py publish_outbox) delivers it to Kafka. Exceptions are NOT
    swallowed: if the event cannot be recorded, the booking must not commit
    without it.
    """
    from .outbox import enqueue_event
    return enqueue_event(TOPIC_BOOKING_CREATED, {
        'booking_id': str(booking.id),
        'user_id': str(booking.user.id),
        'user_email': booking.user.email,
        'total_amount': str(booking.total_amount),
        'status': booking.status,
        'check_in': str(booking.check_in),
        'check_out': str(booking.check_out),
    })