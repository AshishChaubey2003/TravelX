"""
F-008 — lease-ownership tests for the outbox relay.

HONESTY NOTE: these use the FakeProducer contract (produce/flush/callback)
and SQLite. They prove the relay's OWN state machine — lease scoping, stale
finalizers, watchdog rescue, retry/dead transitions, stable event ids —
never real broker behaviour or real FOR UPDATE serialisation. Broker
integration remains BLOCKED without a Kafka test broker.
"""
import json
import uuid as uuid_module
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.kafka_events.models import OutboxEvent
from apps.kafka_events.outbox import (
    enqueue_event,
    publish_pending_events,
    rescue_stale_inflight_events,
)
from apps.kafka_events.topics import TOPIC_PAYMENT_FAILED

BOOKING_ID = "11111111-2222-3333-4444-555555555555"


def _payload():
    return {
        "booking_id": BOOKING_ID,
        "user_id": "7",
        "user_email": "guest@example.com",
        "total_amount": "4500.00",
    }


class FakeProducer:
    def __init__(self, error=None, confirm=True):
        self.error = error
        self.confirm = confirm
        self.produced = []
        self._callbacks = []

    def produce(self, topic, key, value, callback):
        self.produced.append({"topic": topic, "key": key, "value": value})
        self._callbacks.append(callback)

    def flush(self, timeout=None):
        if self.confirm:
            for callback in self._callbacks:
                callback(self.error, mock.MagicMock())
        self._callbacks = []
        return 0


def _relay(fake, **kwargs):
    with mock.patch("apps.kafka_events.outbox.get_producer", return_value=fake):
        return publish_pending_events(**kwargs)


class LeaseLifecycleTests(TestCase):
    def test_successful_pass_reserves_publishes_and_clears_the_lease(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        summary = _relay(FakeProducer())
        row.refresh_from_db()
        self.assertEqual(summary, {"published": 1, "failed": 0, "dead": 0})
        self.assertEqual(row.status, "PUBLISHED")
        self.assertIsNone(row.lease_id)       # lease released on finalize
        self.assertIsNone(row.inflight_at)
        self.assertIsNotNone(row.published_at)

    def test_delivery_failure_returns_to_pending_with_backoff_and_no_lease(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        before = timezone.now()
        summary = _relay(FakeProducer(error="broker unavailable"))
        row.refresh_from_db()
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(row.status, "PENDING")
        self.assertEqual(row.attempts, 1)
        self.assertIsNone(row.lease_id)
        self.assertGreater(row.next_attempt_at, before)

    def test_missing_callback_result_is_never_interpreted_as_delivered(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        summary = _relay(FakeProducer(confirm=False))  # callbacks never fire
        row.refresh_from_db()
        self.assertEqual(summary, {"published": 0, "failed": 1, "dead": 0})
        self.assertEqual(row.status, "PENDING")
        self.assertIn("not confirmed", row.last_error)
        self.assertIsNone(row.published_at)

    def test_event_id_is_stable_across_retries(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        fail = FakeProducer(error="down")
        _relay(fail)
        OutboxEvent.objects.filter(pk=row.pk).update(
            next_attempt_at=timezone.now() - timedelta(seconds=1))
        ok = FakeProducer()
        _relay(ok)
        first = json.loads(fail.produced[0]["value"])["event_id"]
        second = json.loads(ok.produced[0]["value"])["event_id"]
        self.assertEqual(first, second)
        self.assertEqual(first, str(row.event_id))  # stamped once at enqueue


class StaleFinalizerTests(TestCase):
    """A finalizer whose lease was lost must write NOTHING."""

    class CrashAfterFlush(Exception):
        pass

    def _relay_interrupted_after_flush(self, during_flush):
        """Run the relay but fire `during_flush` while flush runs (modelling
        another actor acting while this pass's messages are on the wire),
        then let finalize proceed."""
        outer = self

        class InterferingProducer(FakeProducer):
            def flush(self, timeout=None):
                result = super().flush(timeout)
                during_flush()
                return result

        return _relay(InterferingProducer())

    def test_watchdog_rescued_row_is_not_finalized_by_the_old_lease(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())

        def rescue_now():
            # Watchdog fires mid-pass (rescue window elapsed): row returns to
            # PENDING, lease cleared.
            self.assertEqual(rescue_stale_inflight_events(rescue_seconds=0), 1)

        summary = self._relay_interrupted_after_flush(rescue_now)
        row.refresh_from_db()
        # The old pass observed a positive ack, but its lease is gone: it must
        # write nothing — the row stays PENDING for its new owner.
        self.assertEqual(summary, {"published": 0, "failed": 0, "dead": 0})
        self.assertEqual(row.status, "PENDING")
        self.assertEqual(row.attempts, 0)
        self.assertIsNone(row.lease_id)

    def test_rereserved_row_is_not_touched_by_the_old_lease_finalizer(self):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        new_lease = uuid_module.uuid4()

        def rescue_and_rereserve():
            rescue_stale_inflight_events(rescue_seconds=0)
            # A second relay pass re-reserves the row under its own lease:
            OutboxEvent.objects.filter(pk=row.pk).update(
                status=OutboxEvent.STATUS_IN_FLIGHT,
                lease_id=new_lease,
                inflight_at=timezone.now(),
            )

        summary = self._relay_interrupted_after_flush(rescue_and_rereserve)
        row.refresh_from_db()
        self.assertEqual(summary, {"published": 0, "failed": 0, "dead": 0})
        self.assertEqual(row.status, "IN_FLIGHT")      # untouched
        self.assertEqual(row.lease_id, new_lease)      # still the new owner's
        self.assertEqual(row.attempts, 0)


class WatchdogTests(TestCase):
    def _stuck_row(self, age_seconds):
        row = enqueue_event(TOPIC_PAYMENT_FAILED, _payload())
        OutboxEvent.objects.filter(pk=row.pk).update(
            status=OutboxEvent.STATUS_IN_FLIGHT,
            lease_id=uuid_module.uuid4(),
            inflight_at=timezone.now() - timedelta(seconds=age_seconds),
        )
        row.refresh_from_db()
        return row

    def test_watchdog_rescues_only_rows_past_the_cutoff(self):
        stuck = self._stuck_row(age_seconds=120)
        fresh = self._stuck_row(age_seconds=5)
        rescued = rescue_stale_inflight_events(rescue_seconds=60)
        stuck.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(rescued, 1)
        self.assertEqual(stuck.status, "PENDING")
        self.assertIsNone(stuck.lease_id)
        self.assertLessEqual(stuck.next_attempt_at, timezone.now())  # due now
        self.assertEqual(fresh.status, "IN_FLIGHT")  # left alone

    @override_settings(OUTBOX_INFLIGHT_RESCUE_SECONDS=10)
    def test_watchdog_cutoff_comes_from_settings_by_default(self):
        stuck = self._stuck_row(age_seconds=11)
        self.assertEqual(rescue_stale_inflight_events(), 1)
        stuck.refresh_from_db()
        self.assertEqual(stuck.status, "PENDING")

    def test_rescued_row_is_republished_and_can_still_go_dead(self):
        stuck = self._stuck_row(age_seconds=120)
        OutboxEvent.objects.filter(pk=stuck.pk).update(attempts=9)  # one left
        rescue_stale_inflight_events(rescue_seconds=60)
        summary = _relay(FakeProducer(error="still down"))
        stuck.refresh_from_db()
        self.assertEqual(summary["dead"], 1)
        self.assertEqual(stuck.status, "DEAD")   # retry policy preserved
        self.assertEqual(stuck.attempts, 10)
