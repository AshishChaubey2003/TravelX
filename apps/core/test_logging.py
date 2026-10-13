import io
import json
import logging

from django.test import SimpleTestCase

from apps.core import logging_utils
from apps.core.logging_utils import (
    JsonFormatter,
    RequestIDFilter,
    bind_request_id,
    get_request_id,
    inject_request_id,
    set_request_id,
    reset_request_id,
    unbind_request_id,
)


class _Capture:
    """Attach a JSON handler (with the request-id filter) to a logger."""

    def __init__(self, name):
        self.logger = logging.getLogger(name)
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(JsonFormatter())
        self.handler.addFilter(RequestIDFilter())

    def __enter__(self):
        self.old_level = self.logger.level
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.DEBUG)
        return self

    def __exit__(self, *exc):
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self.old_level)

    def records(self):
        return [
            json.loads(line)
            for line in self.stream.getvalue().splitlines()
            if line.strip()
        ]


class RequestIDMiddlewareTests(SimpleTestCase):
    URL = "/h01-nonexistent-route/"  # 404 still passes through middleware

    def test_generates_request_id_when_none_supplied(self):
        response = self.client.get(self.URL)
        rid = response["X-Request-ID"]
        self.assertTrue(rid)
        self.assertGreaterEqual(len(rid), 8)

    def test_echoes_valid_incoming_request_id(self):
        response = self.client.get(self.URL, HTTP_X_REQUEST_ID="client-req-12345")
        self.assertEqual(response["X-Request-ID"], "client-req-12345")

    def test_replaces_invalid_incoming_request_id(self):
        response = self.client.get(self.URL, HTTP_X_REQUEST_ID="bad id with spaces!")
        self.assertNotEqual(response["X-Request-ID"], "bad id with spaces!")
        self.assertRegex(response["X-Request-ID"], r"^[A-Za-z0-9._-]{8,64}$")

    def test_replaces_too_short_incoming_request_id(self):
        response = self.client.get(self.URL, HTTP_X_REQUEST_ID="abc")
        self.assertNotEqual(response["X-Request-ID"], "abc")

    def test_context_is_cleared_after_request(self):
        self.client.get(self.URL, HTTP_X_REQUEST_ID="client-req-12345")
        self.assertIsNone(get_request_id())

    def test_request_log_has_id_and_never_the_query_string(self):
        with _Capture("travelx.request") as cap:
            self.client.get(
                self.URL + "?token=supersecret123", HTTP_X_REQUEST_ID="client-req-12345"
            )
        self.assertNotIn("supersecret123", cap.stream.getvalue())
        records = cap.records()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["request_id"], "client-req-12345")
        self.assertEqual(record["path"], self.URL)
        self.assertEqual(record["status"], 404)
        self.assertEqual(record["method"], "GET")
        self.assertIn("duration_ms", record)
        self.assertEqual(record["level"], "WARNING")


class JsonFormatterTests(SimpleTestCase):
    def test_sensitive_extra_fields_are_redacted(self):
        with _Capture("travelx.h01.test") as cap:
            logging.getLogger("travelx.h01.test").info(
                "event",
                extra={
                    "password": "hunter2",
                    "payload": {"api_key": "sk_live_x", "ok": "visible"},
                    "booking_id": "b-1",
                },
            )
        out = cap.stream.getvalue()
        self.assertNotIn("hunter2", out)
        self.assertNotIn("sk_live_x", out)
        record = cap.records()[0]
        self.assertEqual(record["password"], "[REDACTED]")
        self.assertEqual(record["payload"]["api_key"], "[REDACTED]")
        self.assertEqual(record["payload"]["ok"], "visible")
        self.assertEqual(record["booking_id"], "b-1")

    def test_exception_is_included(self):
        with _Capture("travelx.h01.test") as cap:
            try:
                raise ValueError("boom")
            except ValueError:
                logging.getLogger("travelx.h01.test").exception("failed")
        record = cap.records()[0]
        self.assertIn("ValueError: boom", record["exception"])

    def test_record_without_context_has_dash_request_id_via_filter(self):
        with _Capture("travelx.h01.test") as cap:
            logging.getLogger("travelx.h01.test").info("hello")
        self.assertEqual(cap.records()[0]["request_id"], "-")

    def test_context_id_is_used_when_set(self):
        token = set_request_id("ctx-id-123456")
        try:
            with _Capture("travelx.h01.test") as cap:
                logging.getLogger("travelx.h01.test").info("hello")
        finally:
            reset_request_id(token)
        self.assertEqual(cap.records()[0]["request_id"], "ctx-id-123456")


class _FakeRequest:
    def __init__(self, request_id=None):
        if request_id:
            self.request_id = request_id


class _FakeTask:
    def __init__(self, request_id=None):
        self.request = _FakeRequest(request_id)


class CeleryPropagationTests(SimpleTestCase):
    def test_publish_injects_current_request_id(self):
        token = set_request_id("http-req-12345")
        try:
            headers = {}
            inject_request_id(headers=headers)
        finally:
            reset_request_id(token)
        self.assertEqual(headers["request_id"], "http-req-12345")

    def test_publish_without_context_adds_nothing(self):
        headers = {}
        inject_request_id(headers=headers)
        self.assertNotIn("request_id", headers)

    def test_prerun_restores_publisher_id_and_postrun_clears(self):
        bind_request_id(task=_FakeTask("http-req-12345"), task_id="t1")
        self.assertEqual(get_request_id(), "http-req-12345")
        unbind_request_id(task_id="t1")
        self.assertIsNone(get_request_id())

    def test_prerun_without_header_uses_task_id(self):
        bind_request_id(task=_FakeTask(), task_id="t2")
        self.assertEqual(get_request_id(), "task-t2")
        unbind_request_id(task_id="t2")
        self.assertIsNone(get_request_id())

    def test_eager_task_does_not_wipe_outer_request_id(self):
        token = set_request_id("outer-req-1234")
        try:
            bind_request_id(task=_FakeTask(), task_id="t3")
            self.assertEqual(get_request_id(), "outer-req-1234")
            unbind_request_id(task_id="t3")
            self.assertEqual(get_request_id(), "outer-req-1234")
        finally:
            reset_request_id(token)

    def test_connect_is_idempotent(self):
        logging_utils.connect_celery_signals()
        logging_utils.connect_celery_signals()
        self.assertTrue(logging_utils._signals_connected)