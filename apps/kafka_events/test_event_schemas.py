"""
Consumer-loop tests for event validation.

No real Kafka broker is used: run_booking_consumer() is driven with a mocked
consumer, so these prove TravelX's own behaviour (what is dispatched and what
is committed), not real broker behaviour.
"""
import json
from unittest import mock

from django.test import TestCase

from apps.kafka_events.consumers import run_booking_consumer
from apps.kafka_events.topics import TOPIC_PAYMENT_FAILED, TOPIC_PAYMENT_SUCCESS

BOOKING_ID = "11111111-2222-3333-4444-555555555555"

_EXTRA_FIELDS = {
    TOPIC_PAYMENT_SUCCESS: {"amount": "100.00"},
    TOPIC_PAYMENT_FAILED: {"total_amount": "100.00"},
}


def _valid(topic):
    """A payload that passes the schema for `topic` (schema version 1)."""
    payload = {
        "schema_version": 1,
        "booking_id": BOOKING_ID,
        "user_id": "42",
        "user_email": "user@example.com",
    }
    payload.update(_EXTRA_FIELDS[topic])
    return payload


def _message(topic, value, partition=0, offset=0):
    msg = mock.MagicMock()
    msg.error.return_value = None
    msg.topic.return_value = topic
    msg.value.return_value = value
    msg.partition.return_value = partition
    msg.offset.return_value = offset
    return msg


class ConsumerLoopValidationTests(TestCase):
    """Runs run_booking_consumer() against a mocked consumer (no broker)."""

    def _run(self, messages, dispatch_side_effect=None):
        consumer = mock.MagicMock()
        consumer.poll.side_effect = list(messages) + [KeyboardInterrupt()]
        with mock.patch("apps.kafka_events.consumers.get_consumer", return_value=consumer), \
                mock.patch(
                    "apps.kafka_events.consumers.dispatch_event",
                    side_effect=dispatch_side_effect,
                ) as dispatch:
            run_booking_consumer()
        return consumer, dispatch

    def test_unparseable_message_is_committed_and_not_dispatched(self):
        msg = _message(TOPIC_PAYMENT_SUCCESS, b"{not json")
        consumer, dispatch = self._run([msg])
        dispatch.assert_not_called()
        consumer.commit.assert_called_once_with(message=msg, asynchronous=False)
        consumer.close.assert_called_once()

    def test_schema_invalid_message_is_committed_and_not_dispatched(self):
        msg = _message(TOPIC_PAYMENT_SUCCESS, json.dumps({"booking_id": BOOKING_ID}).encode())
        consumer, dispatch = self._run([msg])
        dispatch.assert_not_called()
        consumer.commit.assert_called_once_with(message=msg, asynchronous=False)

    def test_valid_message_is_dispatched_then_committed(self):
        msg = _message(TOPIC_PAYMENT_FAILED, json.dumps(_valid(TOPIC_PAYMENT_FAILED)).encode())
        consumer, dispatch = self._run([msg])
        dispatch.assert_called_once()
        called_topic, called_payload = dispatch.call_args.args
        self.assertEqual(called_topic, TOPIC_PAYMENT_FAILED)
        self.assertEqual(called_payload["booking_id"], BOOKING_ID)
        self.assertEqual(called_payload["schema_version"], 1)
        consumer.commit.assert_called_once_with(message=msg, asynchronous=False)

    def test_handler_failure_on_a_valid_message_is_not_committed(self):
        msg = _message(TOPIC_PAYMENT_FAILED, json.dumps(_valid(TOPIC_PAYMENT_FAILED)).encode())
        consumer, dispatch = self._run([msg], dispatch_side_effect=RuntimeError("db down"))
        dispatch.assert_called_once()
        consumer.commit.assert_not_called()  # offset not advanced, so Kafka redelivers

    def test_a_bad_message_does_not_stop_later_good_messages(self):
        bad = _message(TOPIC_PAYMENT_FAILED, b"{broken", offset=0)
        good = _message(TOPIC_PAYMENT_FAILED, json.dumps(_valid(TOPIC_PAYMENT_FAILED)).encode(), offset=1)
        consumer, dispatch = self._run([bad, good])
        dispatch.assert_called_once()
        self.assertEqual(consumer.commit.call_count, 2)