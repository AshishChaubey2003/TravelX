import importlib.util
import sys
from io import StringIO
from unittest import mock, skipUnless

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from apps.core.error_tracking import IGNORED_LOGGERS, init_sentry, scrub_event
from apps.core.logging_utils import REDACTED, reset_request_id, set_request_id

HAS_SDK = importlib.util.find_spec("sentry_sdk") is not None


class ScrubEventTests(SimpleTestCase):
    def test_adds_request_id_tag_when_context_is_set(self):
        token = set_request_id("http-req-12345")
        try:
            event = scrub_event({"tags": {"a": "b"}})
        finally:
            reset_request_id(token)
        self.assertEqual(event["tags"]["request_id"], "http-req-12345")
        self.assertEqual(event["tags"]["a"], "b")

    def test_creates_tags_dict_when_missing(self):
        token = set_request_id("http-req-12345")
        try:
            event = scrub_event({})
        finally:
            reset_request_id(token)
        self.assertEqual(event["tags"], {"request_id": "http-req-12345"})

    def test_no_request_id_means_no_tag(self):
        self.assertNotIn("tags", scrub_event({}))

    def test_strips_query_string_cookies_and_body(self):
        event = scrub_event(
            {
                "request": {
                    "url": "http://x/y",
                    "query_string": "token=secret123",
                    "cookies": {"sessionid": "abc"},
                    "data": {"password": "hunter2"},
                }
            }
        )
        request = event["request"]
        self.assertEqual(request["url"], "http://x/y")
        for key in ("query_string", "cookies", "data"):
            self.assertNotIn(key, request)

    def test_redacts_sensitive_headers_only(self):
        event = scrub_event(
            {
                "request": {
                    "headers": {
                        "Authorization": "Bearer abc",
                        "Cookie": "sessionid=1",
                        "X-Razorpay-Signature": "sig",
                        "User-Agent": "curl/8",
                    }
                }
            }
        )
        headers = event["request"]["headers"]
        self.assertEqual(headers["Authorization"], REDACTED)
        self.assertEqual(headers["Cookie"], REDACTED)
        self.assertEqual(headers["X-Razorpay-Signature"], REDACTED)
        self.assertEqual(headers["User-Agent"], "curl/8")

    def test_redacts_extra_and_removes_user(self):
        event = scrub_event(
            {
                "extra": {"api_key": "k", "nested": {"password": "p"}, "booking_id": "b-1"},
                "user": {"id": 1, "email": "a@b.c", "ip_address": "1.2.3.4"},
            }
        )
        self.assertEqual(event["extra"]["api_key"], REDACTED)
        self.assertEqual(event["extra"]["nested"]["password"], REDACTED)
        self.assertEqual(event["extra"]["booking_id"], "b-1")
        self.assertNotIn("user", event)

    def test_event_is_never_dropped(self):
        self.assertIsNotNone(scrub_event({"message": "x"}))


class InitSentryTests(SimpleTestCase):
    def test_empty_dsn_returns_false_and_does_not_import_the_sdk(self):
        with mock.patch.dict(sys.modules, {"sentry_sdk": None}):
            self.assertFalse(init_sentry(""))

    def test_missing_sdk_returns_false(self):
        with mock.patch.dict(sys.modules, {"sentry_sdk": None}):
            self.assertFalse(init_sentry("https://k@example.invalid/1"))

    @skipUnless(HAS_SDK, "sentry-sdk not installed")
    def test_init_uses_privacy_safe_options(self):
        with mock.patch("sentry_sdk.init") as fake_init:
            result = init_sentry(
                "https://k@example.invalid/1",
                environment="staging",
                release="abc123",
                traces_sample_rate=0.1,
            )
        self.assertTrue(result)
        kwargs = fake_init.call_args.kwargs
        self.assertFalse(kwargs["send_default_pii"])
        self.assertFalse(kwargs["include_local_variables"])
        self.assertEqual(kwargs["max_request_body_size"], "never")
        self.assertEqual(kwargs["environment"], "staging")
        self.assertEqual(kwargs["release"], "abc123")
        self.assertEqual(kwargs["traces_sample_rate"], 0.1)
        self.assertIs(kwargs["before_send"], scrub_event)

    @skipUnless(HAS_SDK, "sentry-sdk not installed")
    def test_request_and_health_loggers_are_ignored(self):
        with mock.patch("sentry_sdk.init"), mock.patch(
            "sentry_sdk.integrations.logging.ignore_logger"
        ) as fake_ignore:
            init_sentry("https://k@example.invalid/1")
        ignored = {call.args[0] for call in fake_ignore.call_args_list}
        self.assertEqual(ignored, set(IGNORED_LOGGERS))


class SentryCheckCommandTests(SimpleTestCase):
    @override_settings(SENTRY_DSN="")
    def test_command_refuses_without_dsn(self):
        with self.assertRaises(CommandError):
            call_command("sentry_check")

    @skipUnless(HAS_SDK, "sentry-sdk not installed")
    @override_settings(SENTRY_DSN="https://k@example.invalid/1")
    def test_command_sends_one_event_and_flushes(self):
        out = StringIO()
        with mock.patch("sentry_sdk.capture_exception", return_value="evt123") as cap, \
                mock.patch("sentry_sdk.flush") as flush:
            call_command("sentry_check", stdout=out)
        cap.assert_called_once()
        flush.assert_called_once()
        self.assertIn("evt123", out.getvalue())