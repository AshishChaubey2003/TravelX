import json
import logging
from confluent_kafka import Producer
from django.conf import settings
from .schemas import EventValidationError, prepare_event
from .topics import (
    TOPIC_BOOKING_CREATED,
    TOPIC_PAYMENT_SUCCESS,
    TOPIC_PAYMENT_FAILED,
    TOPIC_BOOKING_CANCELLED,
)

logger = logging.getLogger(__name__)

_producer = None


def get_producer():
    global _producer
    if _producer is None:
        _producer = Producer({
            'bootstrap.servers': settings.KAFKA_BROKER,
            'socket.timeout.ms': 5000,
            'message.timeout.ms': 5000,
        })
    return _producer


def delivery_report(err, msg):
    if err:
        logger.error(f'Kafka delivery failed: {err}')
    else:
        logger.info(f'Event delivered to {msg.topic()} [{msg.partition()}]')


def publish_event(topic: str, payload: dict):
    # G06: stamp schema_version and validate before publishing. An invalid
    # event is logged and NOT published (same "log, don't raise" policy as
    # Kafka failures below).
    try:
        event = prepare_event(topic, payload)
    except EventValidationError as e:
        logger.error(f'Refusing to publish invalid {topic} event: {e}')
        return

    try:
        producer = get_producer()
        producer.produce(
            topic=topic,
            key=str(event.get('booking_id', 'unknown')).encode(),
            value=json.dumps(event).encode(),
            callback=delivery_report,
        )
        producer.poll(0)  # non-blocking
        logger.info(f'Event published to {topic}: {event}')
    except Exception as e:
        logger.error(f'Kafka publish failed: {e}')


def publish_booking_created(booking):
    """
    G08: does NOT talk to Kafka. Writes the booking.created event to the
    transactional outbox, so it must be called inside the same database
    transaction that creates the booking. The relay
    (manage.py publish_outbox) delivers it to Kafka. Exceptions are NOT
    swallowed: if the event cannot be recorded, the booking must not commit
    without it.

    (The name is kept for backwards compatibility with existing callers and
    tests; it may be renamed in a later cleanup.)
    """
    from .outbox import enqueue_event
    enqueue_event(TOPIC_BOOKING_CREATED, {
        'booking_id': str(booking.id),
        'user_id': str(booking.user.id),
        'user_email': booking.user.email,
        'total_amount': str(booking.total_amount),
        'status': booking.status,
        'check_in': str(booking.check_in),
        'check_out': str(booking.check_out),
    })


def publish_payment_success(booking, payment):
    publish_event(TOPIC_PAYMENT_SUCCESS, {
        'booking_id': str(booking.id),
        'user_id': str(booking.user.id),
        'user_email': booking.user.email,
        'amount': str(payment.amount),
        'stripe_session_id': payment.stripe_session_id,
    })


def publish_payment_failed(booking):
    publish_event(TOPIC_PAYMENT_FAILED, {
        'booking_id': str(booking.id),
        'user_id': str(booking.user.id),
        'user_email': booking.user.email,
        'total_amount': str(booking.total_amount),
    })


def publish_booking_cancelled(booking):
    publish_event(TOPIC_BOOKING_CANCELLED, {
        'booking_id': str(booking.id),
        'user_id': str(booking.user.id),
        'user_email': booking.user.email,
        'total_amount': str(booking.total_amount),
    })