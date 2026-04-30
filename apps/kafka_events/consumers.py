import json
import logging
from confluent_kafka import Consumer, KafkaError
from django.conf import settings
from .topics import (
    TOPIC_BOOKING_CREATED,
    TOPIC_PAYMENT_SUCCESS,
    TOPIC_PAYMENT_FAILED,
    TOPIC_BOOKING_CANCELLED,
)

logger = logging.getLogger(__name__)


def get_consumer(group_id: str):
    return Consumer({
        'bootstrap.servers': settings.KAFKA_BROKER,
        'group.id': group_id,
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False,
    })


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
            payload = json.loads(msg.value().decode('utf-8'))

            logger.info(f'Received event from {topic}: {payload}')

            try:
                if topic == TOPIC_BOOKING_CREATED:
                    handle_booking_created(payload)

                elif topic == TOPIC_PAYMENT_SUCCESS:
                    handle_payment_success(payload)

                elif topic == TOPIC_PAYMENT_FAILED:
                    handle_payment_failed(payload)

                elif topic == TOPIC_BOOKING_CANCELLED:
                    handle_booking_cancelled(payload)

                # Manual commit after successful processing
                consumer.commit(msg)

            except Exception as e:
                logger.error(f'Error processing event {topic}: {e}')

    except KeyboardInterrupt:
        logger.info('Consumer stopped by user')
    finally:
        consumer.close()


def handle_booking_created(payload):
    from tasks.email_tasks import send_booking_confirmation
    booking_id = payload.get('booking_id')
    logger.info(f'Booking created: {booking_id}')
    # Trigger Celery email task
    send_booking_confirmation.delay(booking_id)


def handle_payment_success(payload):
    from tasks.email_tasks import send_payment_receipt
    from apps.bookings.models import Booking
    booking_id = payload.get('booking_id')
    logger.info(f'Payment success: {booking_id}')
    # Update booking status
    try:
        booking = Booking.objects.get(id=booking_id)
        booking.status = 'PAID'
        booking.save()
        # Trigger receipt email
        send_payment_receipt.delay(booking_id)
    except Exception as e:
        logger.error(f'Error updating booking status: {e}')


def handle_payment_failed(payload):
    from apps.bookings.models import Booking
    booking_id = payload.get('booking_id')
    logger.info(f'Payment failed: {booking_id}')
    try:
        booking = Booking.objects.get(id=booking_id)
        booking.status = 'CANCELLED'
        booking.save()
    except Exception as e:
        logger.error(f'Error cancelling booking: {e}')


def handle_booking_created(payload):
    from apps.tasks.email_tasks import send_booking_confirmation
    # ya abhi ke liye sirf log karo:
    booking_id = payload.get('booking_id')
    logger.info(f'Booking created event received: {booking_id}')