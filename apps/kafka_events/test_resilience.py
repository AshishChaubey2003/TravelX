"""
Resilience scenarios (checklist G12): duplicate events, worker restarts,
broker outages and retry exhaustion.

These tests run the REAL consumer loop, handlers, Celery tasks (in-process,
see conftest.py), outbox relay and recovery functions against the real test
database. Only the outside world is simulated:
  - the Kafka consumer is a mock that is scripted to deliver messages
    (including redeliveries after a rewind or restart),
  - the Kafka producer is a fake that records what reaches the "wire",
  - SMTP is Django's in-memory email backend (mail.outbox).

So they prove TravelX's own behaviour under these failures. They do NOT prove
real broker behaviour (rebalances, actual seek(), network partitions); that
needs the manual drills described with the Phase 2 criteria.
"""
import contextlib
import json
import uuid
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.bookings.models import Booking, EmailNotification
from apps.bookings.tasks import (
    send_booking_confirmation,
    send_payment_receipt,
)
from apps.kafka_events import recovery
from apps.kafka_events.consumers import run_booking_consumer
from apps.kafka_events.models import (
    FailedEvent,
    FailedTask,
    OutboxEvent,
    ProcessedEvent,
)
from apps.kafka_events.outbox import publish_pending_events
from apps.kafka_events.producers import publish_booking_created
from apps.kafka_events.topics import (
    TOPIC_BOOKING_CREATED,
    TOPIC_PAYMENT_FAILED,
    TOPIC_PAYMENT_SUCCESS,
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _make_booking(status="PENDING", username="resilience_user"):
    user = User.objects.create_user(username=username, email=f"{username}@example.com", password="x")
    return Booking.objects.create(
        user=user,
        status=status,
        total_amount=1000,
        check_in="2026-11-01",
        check_out="2026-11-02",
    )


def _event_for(topic, booking, event_id="auto", **extra):
    """A schema-valid event for the booking. event_id=None omits it (legacy)."""
    event = {
        "booking_id": str(booking.id),
        "user_id": str(booking.user_id),
        "user_email": booking.user.email,
    }
    if topic == TOPIC_BOOKING_CREATED:
        event.update(total_amount="1000.00", status=booking.status,
                     check_in="2026-11-01", check_out="2026-11-02")
    elif topic == TOPIC_PAYMENT_SUCCESS:
        event.update(amount="1000.00")
    else:
        event.update(total_amount="1000.00")
    if event_id == "auto":
        event["event_id"] = str(uuid.uuid4())
    elif event_id is not None:
        event["event_id"] = event_id
    event.update(extra)
    return event


def _kafka_message(topic, event, partition=0, offset=0):
    msg = mock.MagicMock()
    msg.error.return_value = None
    msg.topic.return_value = topic
    msg.value.return_value = json.dumps(event).encode()
    msg.partition.return_value = partition
    msg.offset.return_value = offset
    return msg


def _run_consumer(messages, consumer=None):
    """
    Run the real run_booking_consumer() against a scripted mock consumer. The
    loop ends when the scripted poll() raises KeyboardInterrupt. Real handlers
    and the real ledger/dead-letter code run; rewind and sleep are mocked.
    Returns (consumer, rewind_mock).
    """
    consumer = consumer if consumer is not None else mock.MagicMock()
    consumer.poll.side_effect = list(messages) + [KeyboardInterrupt()]
    with mock.patch("apps.kafka_events.consumers.get_consumer", return_value=consumer), \
            mock.patch("apps.kafka_events.consumers._rewind") as rewind, \
            mock.patch("apps.kafka_events.consumers.time.sleep"):
        run_booking_consumer()
    return consumer, rewind


class WireProducer:
    """
    Fake confluent-kafka producer. Messages that are delivered end up in the
    shared `wire` list. error=... simulates a broker outage (nothing reaches
    the wire, the delivery callback reports the error). die_after_flush=True
    simulates the relay process being killed right after the broker accepted
    the messages but before the relay recorded that in the database.
    """

    def __init__(self, wire, error=None, die_after_flush=False):
        self.wire = wire
        self.error = error
        self.die_after_flush = die_after_flush
        self._pending = []

    def produce(self, topic, key, value, callback):
        self._pending.append((topic, key, value, callback))

    def flush(self, timeout=None):
        for topic, key, value, callback in self._pending:
            if self.error is None:
                self.wire.append({"topic": topic, "key": key, "value": value})
            callback(self.error, mock.MagicMock())
        self._pending = []
        if self.die_after_flush:
            raise RuntimeError("relay process killed")
        return 0


def _relay(producer, **kwargs):
    with mock.patch("apps.kafka_events.outbox.get_producer", return_value=producer):
        return publish_pending_events(**kwargs)


def _make_everything_due():
    OutboxEvent.objects.update(next_attempt_at=timezone.now() - timedelta(seconds=1))


@contextlib.contextmanager
def _eager_errors_captured():
    """
    conftest.py makes Celery re-raise task errors in-process. For retry
    exhaustion we want the failed result instead of an exception.
    """
    from config.celery import app

    previous = app.conf.task_eager_propagates
    app.conf.task_eager_propagates = False
    try:
        yield
    finally:
        app.conf.task_eager_propagates = previous


# --------------------------------------------------------------------------
# duplicate events
# --------------------------------------------------------------------------

class DuplicateEventScenarios(TestCase):
    def test_payment_success_delivered_twice_has_one_effect_and_one_receipt(self):
        booking = _make_booking()
        event = _event_for(TOPIC_PAYMENT_SUCCESS, booking)
        first = _kafka_message(TOPIC_PAYMENT_SUCCESS, event, offset=1)
        again = _kafka_message(TOPIC_PAYMENT_SUCCESS, event, offset=1)

        consumer, _ = _run_consumer([first, again])

        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(ProcessedEvent.objects.count(), 1)
        self.assertEqual(consumer.commit.call_count, 2)  # the duplicate is still acknowledged

    def test_same_event_id_at_a_different_offset_is_still_a_duplicate(self):
        booking = _make_booking()
        event = _event_for(TOPIC_BOOKING_CREATED, booking)
        first = _kafka_message(TOPIC_BOOKING_CREATED, event, offset=1)
        republished = _kafka_message(TOPIC_BOOKING_CREATED, event, offset=57)

        _run_consumer([first, republished])

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(ProcessedEvent.objects.count(), 1)

    def test_two_different_events_for_one_payment_still_send_one_receipt(self):
        booking = _make_booking()
        first = _kafka_message(TOPIC_PAYMENT_SUCCESS, _event_for(TOPIC_PAYMENT_SUCCESS, booking), offset=1)
        second = _kafka_message(TOPIC_PAYMENT_SUCCESS, _event_for(TOPIC_PAYMENT_SUCCESS, booking), offset=2)

        _run_consumer([first, second])

        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")
        self.assertEqual(ProcessedEvent.objects.count(), 2)  # two distinct events
        self.assertEqual(len(mail.outbox), 1)                # but one email (G03)
        self.assertEqual(EmailNotification.objects.filter(booking=booking, status="SENT").count(), 1)

    def test_legacy_event_without_event_id_redelivered_at_the_same_offset(self):
        booking = _make_booking()
        legacy = _event_for(TOPIC_PAYMENT_SUCCESS, booking, event_id=None)
        first = _kafka_message(TOPIC_PAYMENT_SUCCESS, legacy, partition=0, offset=9)
        replay = _kafka_message(TOPIC_PAYMENT_SUCCESS, legacy, partition=0, offset=9)

        _run_consumer([first, replay])

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(ProcessedEvent.objects.count(), 1)

    def test_a_late_payment_failed_after_success_does_not_cancel_the_booking(self):
        booking = _make_booking()
        success = _kafka_message(TOPIC_PAYMENT_SUCCESS, _event_for(TOPIC_PAYMENT_SUCCESS, booking), offset=1)
        late_failure = _kafka_message(TOPIC_PAYMENT_FAILED, _event_for(TOPIC_PAYMENT_FAILED, booking), offset=2)

        _run_consumer([success, late_failure])

        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")


# --------------------------------------------------------------------------
# worker restarts
# --------------------------------------------------------------------------

class WorkerRestartScenarios(TestCase):
    def test_consumer_killed_after_processing_but_before_commit(self):
        booking = _make_booking()
        event = _event_for(TOPIC_PAYMENT_SUCCESS, booking)
        message = _kafka_message(TOPIC_PAYMENT_SUCCESS, event, offset=5)

        # Process 1: the event is fully processed, then the process is killed
        # exactly when it tries to commit the offset.
        dying = mock.MagicMock()
        dying.commit.side_effect = KeyboardInterrupt()
        _run_consumer([message], consumer=dying)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")
        self.assertEqual(len(mail.outbox), 1)

        # Process 2 (restart): Kafka redelivers the uncommitted message.
        restarted, _ = _run_consumer([_kafka_message(TOPIC_PAYMENT_SUCCESS, event, offset=5)])
        self.assertEqual(len(mail.outbox), 1)               # no second receipt
        self.assertEqual(ProcessedEvent.objects.count(), 1)
        restarted.commit.assert_called_once()                # and it is finally acknowledged

    def test_consumer_killed_in_the_middle_of_a_handler_leaves_nothing_half_applied(self):
        booking = _make_booking()
        event = _event_for(TOPIC_PAYMENT_SUCCESS, booking)

        # Process 1 is killed while the handler is running (after it had
        # already changed the booking's status).
        with mock.patch.object(send_payment_receipt, "delay", side_effect=KeyboardInterrupt()):
            _run_consumer([_kafka_message(TOPIC_PAYMENT_SUCCESS, event, offset=3)])
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PENDING")          # status change rolled back
        self.assertEqual(ProcessedEvent.objects.count(), 0)  # no ledger row
        self.assertEqual(FailedEvent.objects.count(), 0)     # a kill is not a handler failure
        self.assertEqual(len(mail.outbox), 0)

        # Process 2 (restart) handles the redelivered message normally.
        _run_consumer([_kafka_message(TOPIC_PAYMENT_SUCCESS, event, offset=3)])
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")
        self.assertEqual(len(mail.outbox), 1)

    def test_outbox_relay_killed_after_the_broker_accepted_the_event(self):
        booking = _make_booking()
        publish_booking_created(booking)  # writes the outbox row (G08)
        wire = []

        # Relay run 1: Kafka accepted the message, then the relay died before
        # it could finalize. F-008 lease design: the Reserve step had already
        # COMMITTED the row as IN_FLIGHT (produce/flush run outside any
        # transaction), so the crash leaves it IN_FLIGHT — owned by a lease
        # whose pass is dead.
        with self.assertRaises(RuntimeError):
            _relay(WireProducer(wire, die_after_flush=True))
        row = OutboxEvent.objects.get()
        self.assertEqual(row.status, "IN_FLIGHT")
        self.assertIsNotNone(row.lease_id)
        self.assertEqual(len(wire), 1)

        # The watchdog (manual/unscheduled) rescues the stuck row: back to
        # PENDING, lease cleared so the dead pass can never finalize it.
        from apps.kafka_events.outbox import rescue_stale_inflight_events
        self.assertEqual(rescue_stale_inflight_events(rescue_seconds=0), 1)
        row.refresh_from_db()
        self.assertEqual(row.status, "PENDING")
        self.assertIsNone(row.lease_id)

        # Relay run 2 (restart): the event is pending again, so it is sent again.
        summary = _relay(WireProducer(wire))
        self.assertEqual(summary["published"], 1)
        self.assertEqual(OutboxEvent.objects.get().status, "PUBLISHED")
        self.assertEqual(len(wire), 2)
        self.assertEqual(wire[0]["value"], wire[1]["value"])  # same event_id both times

        # The consumer receives both copies but acts once.
        messages = [
            _kafka_message(TOPIC_BOOKING_CREATED, json.loads(item["value"]), offset=index)
            for index, item in enumerate(wire)
        ]
        _run_consumer(messages)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(ProcessedEvent.objects.count(), 1)


# --------------------------------------------------------------------------
# broker outages
# --------------------------------------------------------------------------

class BrokerOutageScenarios(TestCase):
    def test_celery_broker_outage_while_handling_an_event_is_retried_then_succeeds(self):
        booking = _make_booking()
        event = _event_for(TOPIC_PAYMENT_SUCCESS, booking)
        real_delay = send_payment_receipt.delay
        calls = {"n": 0}

        def flaky_delay(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("celery broker down")
            return real_delay(*args, **kwargs)

        # The consumer rewinds and the same message is delivered again.
        messages = [_kafka_message(TOPIC_PAYMENT_SUCCESS, event, offset=4) for _ in range(2)]
        with mock.patch.object(send_payment_receipt, "delay", side_effect=flaky_delay):
            consumer, rewind = _run_consumer(messages)

        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")
        self.assertEqual(calls["n"], 2)
        rewind.assert_called_once()                          # exactly one retry was needed
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(consumer.commit.call_count, 1)      # committed only after success
        self.assertEqual(FailedEvent.objects.get().status, "RESOLVED")

    def test_kafka_commit_outage_does_not_stop_the_consumer_or_duplicate_the_effect(self):
        booking = _make_booking()
        event = _event_for(TOPIC_PAYMENT_SUCCESS, booking)
        consumer = mock.MagicMock()
        consumer.commit.side_effect = [Exception("kafka unavailable"), None]

        # The commit fails, so Kafka redelivers the same message.
        messages = [_kafka_message(TOPIC_PAYMENT_SUCCESS, event, offset=7) for _ in range(2)]
        _run_consumer(messages, consumer=consumer)

        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(consumer.commit.call_count, 2)

    def test_kafka_outage_does_not_affect_bookings_and_the_event_is_delivered_after_recovery(self):
        booking = _make_booking()
        publish_booking_created(booking)
        wire = []

        outage = WireProducer(wire, error="kafka unavailable")
        for _ in range(2):
            _make_everything_due()
            _relay(outage)

        row = OutboxEvent.objects.get()
        self.assertEqual(row.status, "PENDING")
        self.assertEqual(row.attempts, 2)
        self.assertIn("kafka unavailable", row.last_error)
        self.assertEqual(wire, [])
        self.assertTrue(Booking.objects.filter(pk=booking.pk).exists())  # the booking is unaffected

        _make_everything_due()
        _relay(WireProducer(wire))
        self.assertEqual(OutboxEvent.objects.get().status, "PUBLISHED")
        self.assertEqual(len(wire), 1)


# --------------------------------------------------------------------------
# retry exhaustion
# --------------------------------------------------------------------------

class RetryExhaustionScenarios(TestCase):
    @override_settings(KAFKA_CONSUMER_MAX_ATTEMPTS=3)
    def test_consumer_event_is_dead_lettered_then_replayed_once_the_cause_is_fixed(self):
        booking = _make_booking()
        event = _event_for(TOPIC_PAYMENT_SUCCESS, booking)
        messages = [_kafka_message(TOPIC_PAYMENT_SUCCESS, event, offset=2) for _ in range(3)]

        # The Celery broker is down for every attempt.
        with mock.patch.object(send_payment_receipt, "delay", side_effect=ConnectionError("broker down")):
            consumer, rewind = _run_consumer(messages)

        failed = FailedEvent.objects.get()
        self.assertEqual((failed.status, failed.attempts), ("DEAD", 3))
        self.assertEqual(rewind.call_count, 2)               # attempts 1 and 2 were retried
        self.assertEqual(consumer.commit.call_count, 1)      # attempt 3 dead-lettered and moved on
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PENDING")          # nothing half-applied
        self.assertEqual(len(mail.outbox), 0)

        # The broker is fixed; an operator replays the dead event.
        result = recovery.replay_dead_events()
        self.assertEqual(result, {"replayed": 1, "failed": 0})
        failed.refresh_from_db()
        self.assertEqual(failed.status, "REPLAYED")
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")
        self.assertEqual(len(mail.outbox), 1)

        # Replaying again does nothing more.
        self.assertEqual(recovery.replay_dead_events(), {"replayed": 0, "failed": 0})
        self.assertEqual(len(mail.outbox), 1)

    def test_outbox_event_goes_dead_then_is_published_after_replay(self):
        booking = _make_booking()
        publish_booking_created(booking)
        wire = []

        outage = WireProducer(wire, error="kafka unavailable")
        for _ in range(2):
            _make_everything_due()
            _relay(outage, max_attempts=2)

        row = OutboxEvent.objects.get()
        self.assertEqual((row.status, row.attempts), ("DEAD", 2))

        # A dead event is not retried by the relay on its own.
        _make_everything_due()
        _relay(WireProducer(wire))
        self.assertEqual(wire, [])

        # An operator replays it after Kafka is back.
        self.assertEqual(recovery.replay_dead_outbox(), 1)
        _relay(WireProducer(wire))
        self.assertEqual(OutboxEvent.objects.get().status, "PUBLISHED")
        self.assertEqual(len(wire), 1)

    def test_email_task_exhausts_its_retries_is_recorded_then_replayed_after_smtp_recovers(self):
        booking = _make_booking()

        with _eager_errors_captured():
            with mock.patch("apps.bookings.tasks.send_mail", side_effect=OSError("smtp down")) as send:
                result = send_booking_confirmation.apply(args=[str(booking.id)])

        self.assertTrue(result.failed())
        self.assertEqual(send.call_count, send_booking_confirmation.max_retries + 1)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(EmailNotification.objects.filter(booking=booking, status="SENT").exists())

        recorded = FailedTask.objects.get()
        self.assertEqual(recorded.status, "FAILED")
        self.assertEqual(recorded.task_name, send_booking_confirmation.name)
        self.assertEqual(recorded.args, [str(booking.id)])

        # SMTP is back; the operator replays. The replay runs the task
        # in-process instead of through a broker.
        def run_inline(task_name, args=None, kwargs=None):
            send_booking_confirmation.apply(args=args, kwargs=kwargs, throw=True)

        with mock.patch("apps.kafka_events.recovery.current_app") as current_app:
            current_app.send_task.side_effect = run_inline
            outcome = recovery.replay_failed_tasks()

        self.assertEqual(outcome, {"replayed": 1, "failed": 0})
        recorded.refresh_from_db()
        self.assertEqual(recorded.status, "REPLAYED")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [booking.user.email])
        self.assertTrue(EmailNotification.objects.filter(booking=booking, status="SENT").exists())