"""
Tests for the transactional outbox (checklist G08).

The relay is exercised with a FAKE producer that mimics confluent-kafka's
produce/flush/callback contract. These tests prove TravelX's own logic
(atomicity, retry, backoff, dead-lettering, confirmation handling), NOT
behaviour against a real Kafka broker.
"""
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.bookings.models import Booking
from apps.kafka_events.models import OutboxEvent
from apps.kafka_events.outbox import enqueue_event, publish_pending_events
from apps.kafka_events.producers import publish_booking_created
from apps.kafka_events.schemas import EventValidationError, validate_event
from apps.kafka_events.topics import TOPIC_BOOKING_CREATED, TOPIC_PAYMENT_FAILED

BOOKING_ID = "11111111-2222-3333-4444-555555555555"


def _payload(booking_id=BOOKING_ID):
    return {
        "booking_id": booking_id,
        "user_id": "7",
        "user_email": "guest@example.com",
        "total_amount": "4500.00",
    }


def _make_booking(username="outbox_user"):
    user = User.objects.create_user(username=username, email=f"{username}@example.com", password="x")
    return Booking.objects.create(
        user=user,
        status="PENDING",
        total_amount=Decimal("4500.00"),
        check_in="2026-11-01",
        check_out="2026-11-03",
    )


class FakeProducer:
    """Mimics produce()/flush(): delivery callbacks fire during flush()."""

    def __init__(self, error=None, confirm=True, raise_on_produce=None):
        self.error = error
        self.confirm = confirm
        self.raise_on_produce = raise_on_produce
        self.produced = []
        self._callbacks = []

    def produce(self, topic, key, value, callback):
        if self.raise_on_produce is not None:
            raise self.raise_on_produce
        self.produced.append({"topic": topic, "key": key, "value": value})
        self._callbacks.append(callback)

    def flush(self, timeout=None):
        if self.confirm:
            for callback in self._callbacks:
                callback(self.error, mock.MagicMock())
        self._callbacks = []
        return 0


def _run_relay(fake, **kwargs):
    with mock.patch("apps.kafka_events.outbox.get_producer", return_value=fake):
        return publish_pending_events(**kwargs)


class EnqueueTests(TestCase):
    def test_enqueue_writes_a_pending_stamped_and_valid_event(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        row.refresh_from_db()
        self.assertEqual(row.status, "PENDING")
        self.assertEqual(row.attempts, 0)
        self.assertEqual(row.topic, TOPIC_PAYMENT_FAILED)
        self.assertEqual(row.key, BOOKING_ID)
        self.assertEqual(row.payload["schema_version"], 1)
        self.assertEqual(str(row.event_id), row.payload["event_id"])
        validate_event(TOPIC_PAYMENT_FAILED, row.payload)

    def test_invalid_event_raises_and_writes_nothing(self):
        with self.assertRaises(EventValidationError):
            enqueue_event(TOPIC_PAYMENT_FAILED, {"booking_id": BOOKING_ID})
        self.assertEqual(OutboxEvent.objects.count(), 0)

    def test_event_id_is_unique_in_the_database(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OutboxEvent.objects.create(
                    event_id=row.event_id, topic="t", key="k", payload={}
                )


class PublishBookingCreatedTests(TestCase):
    def test_publish_booking_created_enqueues_exactly_one_outbox_row(self):
        booking = _make_booking()
        publish_booking_created(booking)
        row = OutboxEvent.objects.get()
        self.assertEqual(row.topic, TOPIC_BOOKING_CREATED)
        self.assertEqual(row.key, str(booking.id))
        self.assertEqual(row.payload["booking_id"], str(booking.id))
        self.assertEqual(row.payload["total_amount"], "4500.00")
        validate_event(TOPIC_BOOKING_CREATED, row.payload)

    def test_publish_booking_created_does_not_contact_kafka(self):
        booking = _make_booking()
        with mock.patch("apps.kafka_events.producers.get_producer") as get_producer:
            publish_booking_created(booking)
        get_producer.assert_not_called()

    def test_event_and_booking_roll_back_together(self):
        class Boom(Exception):
            pass

        try:
            with transaction.atomic():
                booking = _make_booking()
                publish_booking_created(booking)
                raise Boom()
        except Boom:
            pass
        self.assertEqual(Booking.objects.count(), 0)
        self.assertEqual(OutboxEvent.objects.count(), 0)

    def test_failure_to_enqueue_is_not_swallowed(self):
        booking = _make_booking()
        with mock.patch(
            "apps.kafka_events.outbox.enqueue_event", side_effect=RuntimeError("db write failed")
        ):
            with self.assertRaises(RuntimeError):
                publish_booking_created(booking)


class RelayTests(TestCase):
    def test_pending_event_is_published_and_marked_published(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        fake = FakeProducer()
        summary = _run_relay(fake)
        self.assertEqual(summary, {"published": 1, "failed": 0, "dead": 0})
        self.assertEqual(len(fake.produced), 1)
        sent = fake.produced[0]
        self.assertEqual(sent["topic"], TOPIC_PAYMENT_FAILED)
        self.assertEqual(sent["key"], BOOKING_ID.encode())
        self.assertEqual(json.loads(sent["value"]), row.payload)
        row.refresh_from_db()
        self.assertEqual(row.status, "PUBLISHED")
        self.assertEqual(row.attempts, 1)
        self.assertIsNotNone(row.published_at)

    def test_published_events_are_never_sent_again(self):
        enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        _run_relay(FakeProducer())
        fake = FakeProducer()
        summary = _run_relay(fake)
        self.assertEqual(summary, {"published": 0, "failed": 0, "dead": 0})
        self.assertEqual(fake.produced, [])

    def test_failed_delivery_stays_pending_with_error_and_backoff(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        before = timezone.now()
        summary = _run_relay(FakeProducer(error="broker unavailable"))
        self.assertEqual(summary, {"published": 0, "failed": 1, "dead": 0})
        row.refresh_from_db()
        self.assertEqual(row.status, "PENDING")
        self.assertEqual(row.attempts, 1)
        self.assertIn("broker unavailable", row.last_error)
        self.assertGreater(row.next_attempt_at, before)
        self.assertIsNone(row.published_at)

    def test_event_that_is_not_yet_due_is_skipped(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        row.next_attempt_at = timezone.now() + timedelta(hours=1)
        row.save(update_fields=["next_attempt_at"])
        fake = FakeProducer()
        summary = _run_relay(fake)
        self.assertEqual(summary, {"published": 0, "failed": 0, "dead": 0})
        self.assertEqual(fake.produced, [])

    def test_a_failed_event_is_retried_when_due_and_then_published(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        _run_relay(FakeProducer(error="broker unavailable"))
        OutboxEvent.objects.filter(pk=row.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        summary = _run_relay(FakeProducer())
        self.assertEqual(summary["published"], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, "PUBLISHED")
        self.assertEqual(row.attempts, 2)
        self.assertEqual(row.last_error, "")

    def test_event_becomes_dead_after_max_attempts_and_is_not_retried(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        summary = _run_relay(FakeProducer(error="broker unavailable"), max_attempts=1)
        self.assertEqual(summary, {"published": 0, "failed": 0, "dead": 1})
        row.refresh_from_db()
        self.assertEqual(row.status, "DEAD")
        self.assertIn("broker unavailable", row.last_error)
        fake = FakeProducer()
        self.assertEqual(_run_relay(fake)["published"], 0)
        self.assertEqual(fake.produced, [])

    def test_exception_while_producing_is_recorded_as_a_failure(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        summary = _run_relay(FakeProducer(raise_on_produce=BufferError("queue full")))
        self.assertEqual(summary["failed"], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, "PENDING")
        self.assertIn("queue full", row.last_error)

    def test_unconfirmed_delivery_is_not_marked_published(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        summary = _run_relay(FakeProducer(confirm=False))
        self.assertEqual(summary["failed"], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, "PENDING")
        self.assertIn("not confirmed", row.last_error)

    def test_batch_size_limits_one_pass(self):
        for _ in range(3):
            enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        summary = _run_relay(FakeProducer(), batch_size=2)
        self.assertEqual(summary["published"], 2)
        self.assertEqual(OutboxEvent.objects.filter(status="PENDING").count(), 1)

    def test_events_are_published_in_creation_order(self):
        first = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        second = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        fake = FakeProducer()
        _run_relay(fake)
        sent_ids = [json.loads(item["value"])["event_id"] for item in fake.produced]
        self.assertEqual(sent_ids, [str(first.event_id), str(second.event_id)])


class RelayCommandTests(TestCase):
    def test_publish_outbox_once_processes_pending_events(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        out = StringIO()
        with mock.patch("apps.kafka_events.outbox.get_producer", return_value=FakeProducer()):
            call_command("publish_outbox", "--once", stdout=out)
        row.refresh_from_db()
        self.assertEqual(row.status, "PUBLISHED")
        self.assertIn("published=1", out.getvalue())