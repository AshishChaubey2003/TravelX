"""
Tests for consumer idempotency and offset handling (checklist G07).

No real Kafka broker is used. The consumer-loop tests drive
run_booking_consumer() with a mocked consumer, so they prove TravelX's own
behaviour (ledger, commit calls, rollback) but NOT real broker behaviour.
The ledger itself is exercised against the real test database.
"""
import json
import uuid
from unittest import mock

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.bookings.models import Booking
from apps.bookings.tasks import send_payment_receipt
from apps.kafka_events.consumers import (
    build_event_key,
    process_event_once,
    run_booking_consumer,
)
from apps.kafka_events.models import ProcessedEvent
from apps.kafka_events.topics import TOPIC_PAYMENT_FAILED, TOPIC_PAYMENT_SUCCESS

BOOKING_ID = "11111111-2222-3333-4444-555555555555"


def _message(topic, value, partition=0, offset=0):
    msg = mock.MagicMock()
    msg.error.return_value = None
    msg.topic.return_value = topic
    msg.value.return_value = value
    msg.partition.return_value = partition
    msg.offset.return_value = offset
    return msg


def _failed_event(**overrides):
    event = {
        "booking_id": BOOKING_ID,
        "user_id": "7",
        "user_email": "guest@example.com",
        "total_amount": "4500.00",
    }
    event.update(overrides)
    return event


def _make_booking(status="PENDING", username="idem_user"):
    user = User.objects.create_user(username=username, email=f"{username}@example.com", password="x")
    return Booking.objects.create(
        user=user,
        status=status,
        total_amount=1000,
        check_in="2026-11-01",
        check_out="2026-11-02",
    )


class EventKeyTests(TestCase):
    def test_key_uses_event_id_when_present(self):
        event_id = str(uuid.uuid4())
        msg = _message(TOPIC_PAYMENT_FAILED, b"", partition=3, offset=99)
        key = build_event_key(TOPIC_PAYMENT_FAILED, {"event_id": event_id}, msg)
        self.assertEqual(key, f"{TOPIC_PAYMENT_FAILED}:event:{event_id}")
        # Flake fix (approved M12): previously `assertNotIn("99", key)` —
        # intended to prove the kafka partition/offset fallback (offset=99)
        # did not leak into the key, but ~8.4% of random UUIDs contain the
        # substring "99", so the test failed on correct behaviour. Assert
        # the absence of the fallback FORMAT instead, which is immune to
        # UUID content. The assertEqual above already pins the exact key.
        self.assertNotIn(":kafka:", key)

    def test_key_falls_back_to_partition_and_offset_for_legacy_events(self):
        msg = _message(TOPIC_PAYMENT_FAILED, b"", partition=3, offset=99)
        key = build_event_key(TOPIC_PAYMENT_FAILED, {}, msg)
        self.assertEqual(key, f"{TOPIC_PAYMENT_FAILED}:kafka:3:99")

    def test_same_event_id_on_different_topics_gives_different_keys(self):
        event_id = str(uuid.uuid4())
        msg = _message("x", b"")
        self.assertNotEqual(
            build_event_key(TOPIC_PAYMENT_FAILED, {"event_id": event_id}, msg),
            build_event_key(TOPIC_PAYMENT_SUCCESS, {"event_id": event_id}, msg),
        )


class ProcessEventOnceTests(TestCase):
    def test_first_delivery_runs_the_handler_and_records_the_event(self):
        with mock.patch("apps.kafka_events.consumers.dispatch_event") as dispatch:
            result = process_event_once(TOPIC_PAYMENT_FAILED, {"a": 1}, "key-1")
        self.assertTrue(result)
        dispatch.assert_called_once_with(TOPIC_PAYMENT_FAILED, {"a": 1})
        record = ProcessedEvent.objects.get(event_key="key-1")
        self.assertEqual(record.topic, TOPIC_PAYMENT_FAILED)

    def test_second_delivery_of_the_same_key_is_skipped(self):
        with mock.patch("apps.kafka_events.consumers.dispatch_event") as dispatch:
            self.assertTrue(process_event_once(TOPIC_PAYMENT_FAILED, {}, "key-1"))
            self.assertFalse(process_event_once(TOPIC_PAYMENT_FAILED, {}, "key-1"))
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(ProcessedEvent.objects.count(), 1)

    def test_different_keys_are_both_processed(self):
        with mock.patch("apps.kafka_events.consumers.dispatch_event") as dispatch:
            process_event_once(TOPIC_PAYMENT_FAILED, {}, "key-1")
            process_event_once(TOPIC_PAYMENT_FAILED, {}, "key-2")
        self.assertEqual(dispatch.call_count, 2)
        self.assertEqual(ProcessedEvent.objects.count(), 2)

    def test_handler_failure_rolls_back_the_ledger_row_so_a_retry_runs(self):
        with mock.patch(
            "apps.kafka_events.consumers.dispatch_event", side_effect=RuntimeError("db down")
        ) as dispatch:
            with self.assertRaises(RuntimeError):
                process_event_once(TOPIC_PAYMENT_FAILED, {}, "key-1")
        self.assertEqual(ProcessedEvent.objects.count(), 0)

        with mock.patch("apps.kafka_events.consumers.dispatch_event") as dispatch_retry:
            self.assertTrue(process_event_once(TOPIC_PAYMENT_FAILED, {}, "key-1"))
        dispatch_retry.assert_called_once()
        self.assertEqual(ProcessedEvent.objects.count(), 1)

    def test_database_rejects_a_duplicate_event_key(self):
        ProcessedEvent.objects.create(event_key="dup", topic="t")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProcessedEvent.objects.create(event_key="dup", topic="t")


class RealHandlerIdempotencyTests(TestCase):
    def test_duplicate_payment_success_queues_only_one_receipt(self):
        booking = _make_booking()
        payload = {"booking_id": str(booking.id)}
        with mock.patch.object(send_payment_receipt, "delay") as delay:
            self.assertTrue(process_event_once(TOPIC_PAYMENT_SUCCESS, payload, "pay-1"))
            self.assertFalse(process_event_once(TOPIC_PAYMENT_SUCCESS, payload, "pay-1"))
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")
        self.assertEqual(delay.call_count, 1)

    def test_handler_failure_after_a_db_change_rolls_that_change_back(self):
        booking = _make_booking()
        payload = {"booking_id": str(booking.id)}
        with mock.patch.object(
            send_payment_receipt, "delay", side_effect=ConnectionError("broker down")
        ):
            with self.assertRaises(ConnectionError):
                process_event_once(TOPIC_PAYMENT_SUCCESS, payload, "pay-1")
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PENDING")  # status change rolled back with the ledger row
        self.assertEqual(ProcessedEvent.objects.count(), 0)


class ConsumerLoopIdempotencyTests(TestCase):
    """Runs run_booking_consumer() against a mocked consumer (no broker)."""

    def _run(self, messages, dispatch_side_effect=None, commit_side_effect=None):
        consumer = mock.MagicMock()
        consumer.poll.side_effect = list(messages) + [KeyboardInterrupt()]
        if commit_side_effect is not None:
            consumer.commit.side_effect = commit_side_effect
        with mock.patch("apps.kafka_events.consumers.get_consumer", return_value=consumer), \
                mock.patch(
                    "apps.kafka_events.consumers.dispatch_event",
                    side_effect=dispatch_side_effect,
                ) as dispatch, \
                mock.patch("apps.kafka_events.consumers._rewind"), \
                mock.patch("apps.kafka_events.consumers.time.sleep"):
            run_booking_consumer()
        return consumer, dispatch

    def test_a_redelivered_event_with_the_same_event_id_is_handled_once(self):
        value = json.dumps(_failed_event(event_id=str(uuid.uuid4()))).encode()
        first = _message(TOPIC_PAYMENT_FAILED, value, offset=1)
        again = _message(TOPIC_PAYMENT_FAILED, value, offset=2)  # same event, new offset
        consumer, dispatch = self._run([first, again])
        self.assertEqual(dispatch.call_count, 1)
        consumer.commit.assert_any_call(message=first, asynchronous=False)
        consumer.commit.assert_any_call(message=again, asynchronous=False)  # duplicate is still acknowledged

    def test_distinct_event_ids_are_both_handled(self):
        a = _message(TOPIC_PAYMENT_FAILED,
                     json.dumps(_failed_event(event_id=str(uuid.uuid4()))).encode(), offset=1)
        b = _message(TOPIC_PAYMENT_FAILED,
                     json.dumps(_failed_event(event_id=str(uuid.uuid4()))).encode(), offset=2)
        consumer, dispatch = self._run([a, b])
        self.assertEqual(dispatch.call_count, 2)

    def test_legacy_event_without_event_id_is_deduped_by_partition_and_offset(self):
        value = json.dumps(_failed_event()).encode()
        first = _message(TOPIC_PAYMENT_FAILED, value, partition=0, offset=5)
        replay = _message(TOPIC_PAYMENT_FAILED, value, partition=0, offset=5)  # same Kafka message
        other = _message(TOPIC_PAYMENT_FAILED, value, partition=0, offset=6)
        consumer, dispatch = self._run([first, replay, other])
        self.assertEqual(dispatch.call_count, 2)  # offsets 5 and 6; the replay of 5 was skipped

    def test_commit_is_synchronous(self):
        msg = _message(TOPIC_PAYMENT_FAILED,
                       json.dumps(_failed_event(event_id=str(uuid.uuid4()))).encode())
        consumer, _ = self._run([msg])
        consumer.commit.assert_called_once_with(message=msg, asynchronous=False)

    def test_failed_handler_is_not_committed_and_leaves_no_ledger_row(self):
        msg = _message(TOPIC_PAYMENT_FAILED,
                       json.dumps(_failed_event(event_id=str(uuid.uuid4()))).encode())
        consumer, dispatch = self._run([msg], dispatch_side_effect=RuntimeError("db down"))
        dispatch.assert_called_once()
        consumer.commit.assert_not_called()
        self.assertEqual(ProcessedEvent.objects.count(), 0)

    def test_commit_failure_does_not_stop_the_consumer(self):
        a = _message(TOPIC_PAYMENT_FAILED,
                     json.dumps(_failed_event(event_id=str(uuid.uuid4()))).encode(), offset=1)
        b = _message(TOPIC_PAYMENT_FAILED,
                     json.dumps(_failed_event(event_id=str(uuid.uuid4()))).encode(), offset=2)
        consumer, dispatch = self._run([a, b], commit_side_effect=Exception("kafka unavailable"))
        self.assertEqual(dispatch.call_count, 2)  # second message still processed
        consumer.close.assert_called_once()