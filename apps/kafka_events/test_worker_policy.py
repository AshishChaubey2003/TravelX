"""
Tests for worker safety rules (checklist G11): booking status transitions
performed by Kafka event handlers, the Celery task allowlist, and the
allowlist on task replay.

Celery's .delay is mocked wherever a receipt could be queued, so no broker or
SMTP server is used.
"""
import logging
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from apps.bookings.models import Booking
from apps.bookings.tasks import send_payment_receipt
from apps.kafka_events import recovery
from apps.kafka_events.consumers import (
    dispatch_event,
    handle_payment_failed,
    handle_payment_success,
    run_booking_consumer,
)
from apps.kafka_events.models import FailedTask
from apps.kafka_events.policy import (
    ALLOWED_TASK_NAMES,
    REPLAYABLE_TASK_NAMES,
    can_transition,
)
from apps.kafka_events.topics import (
    TOPIC_BOOKING_CANCELLED,
    TOPIC_BOOKING_CREATED,
    TOPIC_PAYMENT_FAILED,
    TOPIC_PAYMENT_SUCCESS,
)

ALL_STATUSES = ["PENDING", "CONFIRMED", "PAID", "CANCELLED"]


def _make_booking(status, username=None):
    username = username or f"policy_{status.lower()}"
    user = User.objects.create_user(username=username, email=f"{username}@example.com", password="x")
    return Booking.objects.create(
        user=user,
        status=status,
        total_amount=1000,
        check_in="2026-11-01",
        check_out="2026-11-02",
    )


class TransitionPolicyTests(SimpleTestCase):
    def test_paid_is_reachable_only_from_pending_and_confirmed(self):
        allowed = {s for s in ALL_STATUSES if can_transition(s, "PAID")}
        self.assertEqual(allowed, {"PENDING", "CONFIRMED"})

    def test_cancelled_is_reachable_only_from_pending_and_confirmed(self):
        allowed = {s for s in ALL_STATUSES if can_transition(s, "CANCELLED")}
        self.assertEqual(allowed, {"PENDING", "CONFIRMED"})

    def test_unknown_target_statuses_are_never_allowed(self):
        for current in ALL_STATUSES:
            self.assertFalse(can_transition(current, "REFUNDED"))
            self.assertFalse(can_transition(current, "PENDING"))
            self.assertFalse(can_transition(current, "CONFIRMED"))


class PaymentSuccessGuardTests(TestCase):
    def _handle(self, booking):
        with mock.patch.object(send_payment_receipt, "delay") as delay:
            handle_payment_success({"booking_id": str(booking.id)})
        booking.refresh_from_db()
        return delay

    def test_pending_booking_becomes_paid_and_gets_a_receipt(self):
        booking = _make_booking("PENDING")
        delay = self._handle(booking)
        self.assertEqual(booking.status, "PAID")
        delay.assert_called_once_with(str(booking.id))

    def test_confirmed_booking_becomes_paid(self):
        booking = _make_booking("CONFIRMED")
        self._handle(booking)
        self.assertEqual(booking.status, "PAID")

    def test_already_paid_booking_stays_paid_and_receipt_is_still_queued(self):
        booking = _make_booking("PAID")
        delay = self._handle(booking)
        self.assertEqual(booking.status, "PAID")
        delay.assert_called_once_with(str(booking.id))  # the receipt task itself is idempotent (G03)

    def test_cancelled_booking_is_never_marked_paid(self):
        booking = _make_booking("CANCELLED")
        with self.assertLogs("apps.kafka_events.consumers", level=logging.ERROR) as captured:
            delay = self._handle(booking)
        self.assertEqual(booking.status, "CANCELLED")
        delay.assert_not_called()
        self.assertIn("manual review", "\n".join(captured.output))

    def test_handler_only_writes_the_status_field(self):
        booking = _make_booking("PENDING")
        with mock.patch.object(Booking, "save", autospec=True) as save, \
                mock.patch.object(send_payment_receipt, "delay"):
            handle_payment_success({"booking_id": str(booking.id)})
        save.assert_called_once()
        self.assertEqual(save.call_args.kwargs["update_fields"], ["status"])

    def test_other_booking_fields_are_untouched(self):
        booking = _make_booking("PENDING")
        booking.refresh_from_db()
        before = (booking.total_amount, booking.check_in, booking.check_out, booking.user_id)
        self._handle(booking)
        after = (booking.total_amount, booking.check_in, booking.check_out, booking.user_id)
        self.assertEqual(before, after)


class PaymentFailedGuardTests(TestCase):
    def _handle(self, booking):
        handle_payment_failed({"booking_id": str(booking.id)})
        booking.refresh_from_db()

    def test_pending_booking_is_cancelled(self):
        booking = _make_booking("PENDING")
        self._handle(booking)
        self.assertEqual(booking.status, "CANCELLED")

    def test_confirmed_booking_is_cancelled(self):
        booking = _make_booking("CONFIRMED")
        self._handle(booking)
        self.assertEqual(booking.status, "CANCELLED")

    def test_paid_booking_is_never_cancelled_by_a_failure_event(self):
        booking = _make_booking("PAID")
        with self.assertLogs("apps.kafka_events.consumers", level=logging.WARNING) as captured:
            self._handle(booking)
        self.assertEqual(booking.status, "PAID")
        self.assertIn("ignored", "\n".join(captured.output))

    def test_already_cancelled_booking_is_left_alone(self):
        booking = _make_booking("CANCELLED")
        self._handle(booking)
        self.assertEqual(booking.status, "CANCELLED")

    def test_success_then_failure_keeps_the_booking_paid(self):
        booking = _make_booking("PENDING")
        with mock.patch.object(send_payment_receipt, "delay"):
            handle_payment_success({"booking_id": str(booking.id)})
        self._handle(booking)
        self.assertEqual(booking.status, "PAID")


class ConsumerScopeTests(TestCase):
    def test_consumer_subscribes_only_to_the_four_known_topics(self):
        consumer = mock.MagicMock()
        consumer.poll.side_effect = [KeyboardInterrupt()]
        with mock.patch("apps.kafka_events.consumers.get_consumer", return_value=consumer):
            run_booking_consumer()
        subscribed = consumer.subscribe.call_args.args[0]
        self.assertEqual(
            set(subscribed),
            {TOPIC_BOOKING_CREATED, TOPIC_PAYMENT_SUCCESS, TOPIC_PAYMENT_FAILED, TOPIC_BOOKING_CANCELLED},
        )

    def test_an_unknown_topic_performs_no_database_work(self):
        with self.assertNumQueries(0):
            dispatch_event("some.other.topic", {"booking_id": "x"})

    def test_booking_cancelled_event_changes_nothing(self):
        booking = _make_booking("PAID")
        dispatch_event(TOPIC_BOOKING_CANCELLED, {"booking_id": str(booking.id)})
        booking.refresh_from_db()
        self.assertEqual(booking.status, "PAID")


class TaskAllowlistTests(TestCase):
    def test_every_registered_application_task_is_on_the_allowlist(self):
        from config.celery import app

        registered = {name for name in app.tasks if not name.startswith("celery.")}
        unexpected = registered - ALLOWED_TASK_NAMES
        self.assertEqual(
            unexpected, set(),
            f"Tasks registered but not allowlisted (review them, then add to "
            f"apps/kafka_events/policy.py): {sorted(unexpected)}",
        )

    def test_every_allowlisted_task_is_actually_registered(self):
        from config.celery import app
        app.loader.import_default_modules()  # autodiscovery is lazy

        self.assertEqual(ALLOWED_TASK_NAMES - set(app.tasks), set())

    def test_replayable_tasks_are_a_subset_of_allowed_tasks(self):
        self.assertTrue(REPLAYABLE_TASK_NAMES <= ALLOWED_TASK_NAMES)
        self.assertNotIn("config.celery.debug_task", REPLAYABLE_TASK_NAMES)


class ReplayAllowlistTests(TestCase):
    def test_a_non_allowlisted_task_is_refused_and_never_queued(self):
        row = FailedTask.objects.create(
            task_name="os.system", task_id="evil-1", args=["rm -rf /"], kwargs={}
        )
        with mock.patch("apps.kafka_events.recovery.current_app") as current_app:
            result = recovery.replay_failed_tasks()
        current_app.send_task.assert_not_called()
        self.assertEqual(result, {"replayed": 0, "failed": 1})
        row.refresh_from_db()
        self.assertEqual(row.status, "FAILED")
        self.assertIn("not allowlisted", row.replay_error)

    def test_an_allowlisted_task_is_still_replayed(self):
        row = FailedTask.objects.create(
            task_name="apps.bookings.tasks.send_payment_receipt",
            task_id="ok-1", args=["booking-abc"], kwargs={},
        )
        with mock.patch("apps.kafka_events.recovery.current_app") as current_app:
            result = recovery.replay_failed_tasks()
        current_app.send_task.assert_called_once()
        self.assertEqual(result, {"replayed": 1, "failed": 0})
        row.refresh_from_db()
        self.assertEqual(row.status, "REPLAYED")