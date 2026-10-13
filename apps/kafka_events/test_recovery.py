"""
Tests for failure recovery (checklist G10): consumer retry + dead-letter,
failed-task recording, replay operations and the `recovery` command.

The consumer loop is driven with a mocked consumer, and Celery's send_task is
mocked, so these tests prove TravelX's own logic, NOT real broker behaviour.
"""
import json
import sys
import types
import uuid
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.bookings.tasks import send_booking_confirmation
from apps.kafka_events import recovery
from apps.kafka_events.consumers import (
    _rewind,
    record_event_failure,
    run_booking_consumer,
)
from apps.kafka_events.models import (
    FailedEvent,
    FailedTask,
    OutboxEvent,
    ProcessedEvent,
)
from apps.kafka_events.topics import TOPIC_PAYMENT_FAILED

BOOKING_ID = "11111111-2222-3333-4444-555555555555"


def _event(event_id=None):
    return {
        "booking_id": BOOKING_ID,
        "user_id": "7",
        "user_email": "guest@example.com",
        "total_amount": "4500.00",
        "event_id": event_id or str(uuid.uuid4()),
    }


def _message(topic, value, partition=0, offset=0):
    msg = mock.MagicMock()
    msg.error.return_value = None
    msg.topic.return_value = topic
    msg.value.return_value = value
    msg.partition.return_value = partition
    msg.offset.return_value = offset
    return msg


def _key(event):
    return f"{TOPIC_PAYMENT_FAILED}:event:{event['event_id']}"


class RecordEventFailureTests(TestCase):
    def test_attempts_accumulate_and_event_dies_at_the_limit(self):
        event = _event()
        msg = _message(TOPIC_PAYMENT_FAILED, b"", partition=2, offset=17)
        key = _key(event)

        dead, attempts = record_event_failure(TOPIC_PAYMENT_FAILED, key, event, msg, "boom", 3)
        self.assertEqual((dead, attempts), (False, 1))
        row = FailedEvent.objects.get(event_key=key)
        self.assertEqual(row.status, "RETRYING")
        self.assertEqual((row.partition, row.offset), (2, 17))
        self.assertEqual(row.payload, event)
        self.assertIn("boom", row.last_error)

        dead, attempts = record_event_failure(TOPIC_PAYMENT_FAILED, key, event, msg, "boom", 3)
        self.assertEqual((dead, attempts), (False, 2))

        dead, attempts = record_event_failure(TOPIC_PAYMENT_FAILED, key, event, msg, "boom", 3)
        self.assertEqual((dead, attempts), (True, 3))
        row.refresh_from_db()
        self.assertEqual(row.status, "DEAD")
        self.assertIsNotNone(row.dead_at)
        self.assertEqual(FailedEvent.objects.count(), 1)


class RewindTests(TestCase):
    def test_rewind_seeks_back_to_the_failed_offset(self):
        consumer = mock.MagicMock()
        msg = _message("some.topic", b"", partition=4, offset=21)
        fake_module = types.SimpleNamespace(
            TopicPartition=lambda topic, partition, offset: ("tp", topic, partition, offset)
        )
        with mock.patch.dict(sys.modules, {"confluent_kafka": fake_module}):
            _rewind(consumer, msg)
        consumer.seek.assert_called_once_with(("tp", "some.topic", 4, 21))

    def test_rewind_failure_is_logged_not_raised(self):
        consumer = mock.MagicMock()
        consumer.seek.side_effect = Exception("not assigned")
        msg = _message("some.topic", b"", partition=0, offset=1)
        fake_module = types.SimpleNamespace(TopicPartition=lambda *a: a)
        with mock.patch.dict(sys.modules, {"confluent_kafka": fake_module}):
            _rewind(consumer, msg)  # must not raise


class ConsumerRetryAndDeadLetterTests(TestCase):
    def _run(self, messages, dispatch_side_effect=None):
        consumer = mock.MagicMock()
        consumer.poll.side_effect = list(messages) + [KeyboardInterrupt()]
        with mock.patch("apps.kafka_events.consumers.get_consumer", return_value=consumer), \
                mock.patch(
                    "apps.kafka_events.consumers.dispatch_event",
                    side_effect=dispatch_side_effect,
                ) as dispatch, \
                mock.patch("apps.kafka_events.consumers._rewind") as rewind, \
                mock.patch("apps.kafka_events.consumers.time.sleep") as sleep:
            run_booking_consumer()
        return consumer, dispatch, rewind, sleep

    def test_first_failure_rewinds_backs_off_and_does_not_commit(self):
        event = _event()
        msg = _message(TOPIC_PAYMENT_FAILED, json.dumps(event).encode(), offset=8)
        consumer, dispatch, rewind, sleep = self._run([msg], dispatch_side_effect=RuntimeError("db down"))
        consumer.commit.assert_not_called()
        rewind.assert_called_once_with(consumer, msg)
        sleep.assert_called_once_with(2)  # 2 ** attempts(1)
        row = FailedEvent.objects.get(event_key=_key(event))
        self.assertEqual((row.status, row.attempts), ("RETRYING", 1))
        self.assertEqual(ProcessedEvent.objects.count(), 0)

    @override_settings(KAFKA_CONSUMER_MAX_ATTEMPTS=1)
    def test_event_is_dead_lettered_and_committed_at_the_attempt_limit(self):
        event = _event()
        msg = _message(TOPIC_PAYMENT_FAILED, json.dumps(event).encode(), offset=8)
        consumer, dispatch, rewind, sleep = self._run([msg], dispatch_side_effect=RuntimeError("db down"))
        row = FailedEvent.objects.get(event_key=_key(event))
        self.assertEqual(row.status, "DEAD")
        consumer.commit.assert_called_once_with(message=msg, asynchronous=False)
        rewind.assert_not_called()
        sleep.assert_not_called()

    @override_settings(KAFKA_CONSUMER_MAX_ATTEMPTS=3)
    def test_a_poison_message_does_not_block_a_later_good_message_forever(self):
        bad_event, good_event = _event(), _event()
        bad = _message(TOPIC_PAYMENT_FAILED, json.dumps(bad_event).encode(), offset=1)
        good = _message(TOPIC_PAYMENT_FAILED, json.dumps(good_event).encode(), offset=2)

        def dispatch_side_effect(topic, payload):
            if payload["event_id"] == bad_event["event_id"]:
                raise RuntimeError("always fails")

        # The real consumer re-reads the failed message after a rewind; the
        # mocked poll() is scripted to do the same.
        consumer, dispatch, rewind, sleep = self._run(
            [bad, bad, bad, good], dispatch_side_effect=dispatch_side_effect
        )
        self.assertEqual(FailedEvent.objects.get(event_key=_key(bad_event)).status, "DEAD")
        self.assertTrue(ProcessedEvent.objects.filter(event_key=_key(good_event)).exists())
        self.assertEqual(rewind.call_count, 2)  # attempts 1 and 2 rewound; attempt 3 dead-lettered

    def test_a_retrying_event_becomes_resolved_when_it_finally_succeeds(self):
        event = _event()
        FailedEvent.objects.create(
            event_key=_key(event), topic=TOPIC_PAYMENT_FAILED, payload=event,
            status="RETRYING", attempts=1,
        )
        msg = _message(TOPIC_PAYMENT_FAILED, json.dumps(event).encode())
        consumer, dispatch, rewind, sleep = self._run([msg])
        self.assertEqual(FailedEvent.objects.get(event_key=_key(event)).status, "RESOLVED")
        consumer.commit.assert_called_once_with(message=msg, asynchronous=False)

    def test_failure_to_record_the_failure_still_retries_instead_of_losing_the_event(self):
        event = _event()
        msg = _message(TOPIC_PAYMENT_FAILED, json.dumps(event).encode())
        with mock.patch(
            "apps.kafka_events.consumers.record_event_failure", side_effect=Exception("db gone")
        ):
            consumer, dispatch, rewind, sleep = self._run(
                [msg], dispatch_side_effect=RuntimeError("db down")
            )
        consumer.commit.assert_not_called()
        rewind.assert_called_once_with(consumer, msg)


class OutboxReplayTests(TestCase):
    def _outbox(self, status, attempts=10):
        return OutboxEvent.objects.create(
            event_id=uuid.uuid4(), topic="t", key="k", payload={},
            status=status, attempts=attempts, last_error="broker down",
            next_attempt_at=timezone.now() + timedelta(hours=1),
        )

    def test_replay_requeues_only_dead_events(self):
        dead = self._outbox("DEAD")
        published = self._outbox("PUBLISHED", attempts=1)
        pending = self._outbox("PENDING", attempts=2)
        count = recovery.replay_dead_outbox()
        self.assertEqual(count, 1)
        dead.refresh_from_db()
        self.assertEqual((dead.status, dead.attempts, dead.last_error), ("PENDING", 0, ""))
        self.assertLessEqual(dead.next_attempt_at, timezone.now())
        published.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(published.status, "PUBLISHED")
        self.assertEqual((pending.status, pending.attempts), ("PENDING", 2))

    def test_replay_can_be_limited_to_specific_ids(self):
        first, second = self._outbox("DEAD"), self._outbox("DEAD")
        self.assertEqual(recovery.replay_dead_outbox([first.pk]), 1)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.status, second.status), ("PENDING", "DEAD"))


class FailedEventReplayTests(TestCase):
    def _dead(self):
        event = _event()
        return FailedEvent.objects.create(
            event_key=_key(event), topic=TOPIC_PAYMENT_FAILED, payload=event,
            status="DEAD", attempts=5, last_error="db down",
        )

    def test_replay_runs_the_event_and_marks_it_replayed(self):
        row = self._dead()
        with mock.patch("apps.kafka_events.consumers.dispatch_event") as dispatch:
            result = recovery.replay_dead_events()
        self.assertEqual(result, {"replayed": 1, "failed": 0})
        dispatch.assert_called_once_with(row.topic, row.payload)
        row.refresh_from_db()
        self.assertEqual(row.status, "REPLAYED")
        self.assertTrue(ProcessedEvent.objects.filter(event_key=row.event_key).exists())

    def test_failed_replay_keeps_the_event_dead_and_records_the_error(self):
        row = self._dead()
        with mock.patch(
            "apps.kafka_events.consumers.dispatch_event", side_effect=RuntimeError("still broken")
        ):
            result = recovery.replay_dead_events()
        self.assertEqual(result, {"replayed": 0, "failed": 1})
        row.refresh_from_db()
        self.assertEqual(row.status, "DEAD")
        self.assertIn("still broken", row.last_error)
        self.assertFalse(ProcessedEvent.objects.filter(event_key=row.event_key).exists())

    def test_replaying_an_already_processed_event_does_not_run_it_twice(self):
        row = self._dead()
        ProcessedEvent.objects.create(event_key=row.event_key, topic=row.topic)
        with mock.patch("apps.kafka_events.consumers.dispatch_event") as dispatch:
            result = recovery.replay_dead_events()
        dispatch.assert_not_called()
        self.assertEqual(result["replayed"], 1)

    def test_only_dead_events_are_replayed(self):
        row = self._dead()
        FailedEvent.objects.filter(pk=row.pk).update(status="RETRYING")
        with mock.patch("apps.kafka_events.consumers.dispatch_event") as dispatch:
            result = recovery.replay_dead_events()
        dispatch.assert_not_called()
        self.assertEqual(result, {"replayed": 0, "failed": 0})


class FailedTaskTests(TestCase):
    def test_on_failure_records_a_replayable_failed_task(self):
        send_booking_confirmation.on_failure(OSError("smtp down"), "task-1", ("booking-abc",), {}, None)
        row = FailedTask.objects.get(task_id="task-1")
        self.assertEqual(row.task_name, send_booking_confirmation.name)
        self.assertEqual(row.args, ["booking-abc"])
        self.assertEqual(row.kwargs, {})
        self.assertEqual(row.status, "FAILED")
        self.assertIn("smtp down", row.error)

    def test_recording_the_same_task_twice_does_not_duplicate_it(self):
        for _ in range(2):
            send_booking_confirmation.on_failure(OSError("x"), "task-1", ("b",), {}, None)
        self.assertEqual(FailedTask.objects.count(), 1)

    def test_a_bookkeeping_error_never_hides_the_original_failure(self):
        with mock.patch("apps.kafka_events.models.FailedTask.objects") as manager:
            manager.update_or_create.side_effect = Exception("db gone")
            send_booking_confirmation.on_failure(OSError("x"), "task-1", ("b",), {}, None)  # must not raise

    def test_replay_requeues_with_original_arguments_and_marks_replayed(self):
        row = FailedTask.objects.create(
            task_name="apps.bookings.tasks.send_booking_confirmation",
            task_id="task-1", args=["booking-abc"], kwargs={}, error="smtp down",
        )
        with mock.patch("apps.kafka_events.recovery.current_app") as current_app:
            result = recovery.replay_failed_tasks()
        self.assertEqual(result, {"replayed": 1, "failed": 0})
        current_app.send_task.assert_called_once_with(
            "apps.bookings.tasks.send_booking_confirmation", args=["booking-abc"], kwargs={}
        )
        row.refresh_from_db()
        self.assertEqual(row.status, "REPLAYED")
        self.assertIsNotNone(row.replayed_at)

    def test_replay_failure_leaves_the_task_failed_with_the_reason(self):
        row = FailedTask.objects.create(
            task_name="apps.bookings.tasks.send_payment_receipt", task_id="task-1", args=[], kwargs={}
        )
        with mock.patch("apps.kafka_events.recovery.current_app") as current_app:
            current_app.send_task.side_effect = ConnectionError("broker down")
            result = recovery.replay_failed_tasks()
        self.assertEqual(result, {"replayed": 0, "failed": 1})
        row.refresh_from_db()
        self.assertEqual(row.status, "FAILED")
        self.assertIn("broker down", row.replay_error)


class RecoveryCommandTests(TestCase):
    def test_status_reports_counts_for_each_area(self):
        OutboxEvent.objects.create(event_id=uuid.uuid4(), topic="t", key="k", payload={}, status="DEAD")
        FailedEvent.objects.create(event_key="k1", topic="t", payload={}, status="DEAD")
        FailedTask.objects.create(task_name="x", task_id="t1")
        out = StringIO()
        call_command("recovery", "status", stdout=out)
        text = out.getvalue()
        self.assertIn("outbox", text)
        self.assertIn("DEAD", text)
        self.assertIn("failed_events", text)
        self.assertIn("failed_tasks", text)

    def test_status_works_when_everything_is_empty(self):
        out = StringIO()
        call_command("recovery", "status", stdout=out)
        self.assertIn("empty", out.getvalue())

    def test_replay_requires_ids_or_all(self):
        for action in ("replay-outbox", "replay-events", "replay-tasks"):
            with self.assertRaises(CommandError):
                call_command("recovery", action)

    def test_replay_rejects_ids_and_all_together(self):
        with self.assertRaises(CommandError):
            call_command("recovery", "replay-outbox", "--all", "--ids", "1")

    def test_replay_outbox_all_requeues_dead_events(self):
        row = OutboxEvent.objects.create(
            event_id=uuid.uuid4(), topic="t", key="k", payload={}, status="DEAD", attempts=10
        )
        out = StringIO()
        call_command("recovery", "replay-outbox", "--all", stdout=out)
        row.refresh_from_db()
        self.assertEqual(row.status, "PENDING")
        self.assertIn("1", out.getvalue())