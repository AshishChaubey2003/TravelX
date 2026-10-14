"""
Regression lock for the F-007 fix.

Before this change `publish_event` and three descendants (`publish_payment_success`,
`publish_payment_failed`, `publish_booking_cancelled`) called Kafka directly
and swallowed delivery errors. We confirmed by grep that nothing in the
production code or test suite actually called them, so no callers were
broken by the fix — but a future developer who finds the names and uses
them would silently reintroduce the event-loss defect.

These tests pin the new behaviour:
  - Any attempt to call one of the four names now raises RuntimeError.
  - The error message names enqueue_event, so the right API is one grep away.
  - publish_booking_created (which already uses the outbox correctly)
    is untouched.
"""
from unittest.mock import MagicMock

from django.test import TestCase

from apps.kafka_events import producers


class DeprecatedPublishersRaiseTests(TestCase):
    def _assert_deprecated(self, callable_, *args):
        with self.assertRaises(RuntimeError) as ctx:
            callable_(*args)
        self.assertIn("enqueue_event", str(ctx.exception))

    def test_publish_event_raises(self):
        self._assert_deprecated(producers.publish_event, "booking.created", {})

    def test_publish_payment_success_raises(self):
        self._assert_deprecated(
            producers.publish_payment_success, MagicMock(), MagicMock(),
        )

    def test_publish_payment_failed_raises(self):
        self._assert_deprecated(producers.publish_payment_failed, MagicMock())

    def test_publish_booking_cancelled_raises(self):
        self._assert_deprecated(producers.publish_booking_cancelled, MagicMock())
