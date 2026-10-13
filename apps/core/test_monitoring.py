import json
import uuid
from contextlib import ExitStack
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.db.utils import OperationalError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core import monitoring, tasks
from apps.core.monitoring import ThresholdExceeded
from apps.kafka_events.models import FailedEvent, OutboxEvent


def _healthy():
    """Patch the external dependencies so collect() sees them as healthy."""
    stack = ExitStack()
    stack.enter_context(mock.patch("apps.core.health.check_broker", return_value=None))
    stack.enter_context(mock.patch("apps.core.health.check_kafka", return_value=None))
    stack.enter_context(
        mock.patch("apps.core.monitoring.check_celery_workers", return_value={"workers": 1})
    )
    return stack


def _outbox(status=OutboxEvent.STATUS_PENDING):
    return OutboxEvent.objects.create(
        event_id=uuid.uuid4(), topic="booking.created", key="k", payload={}, status=status
    )


class CollectTests(TestCase):
    def test_all_healthy_gives_ok(self):
        with _healthy():
            report = monitoring.collect()
        self.assertEqual(report["status"], "ok")
        self.assertEqual(
            set(report["checks"]),
            {"database", "cache", "broker", "kafka", "celery_workers", "outbox", "dead_letters", "flows"},
        )
        for entry in report["checks"].values():
            self.assertEqual(entry["state"], "ok")
            self.assertIn("latency_ms", entry)

    def test_database_failure_is_down(self):
        with _healthy(), mock.patch(
            "apps.core.health.check_database", side_effect=OperationalError("x")
        ):
            report = monitoring.collect()
        self.assertEqual(report["status"], "down")
        self.assertEqual(report["checks"]["database"]["state"], "fail")
        self.assertTrue(report["checks"]["database"]["critical"])

    def test_kafka_failure_is_degraded_not_down(self):
        with _healthy(), mock.patch(
            "apps.core.health.check_kafka", side_effect=RuntimeError("timeout")
        ):
            report = monitoring.collect()
        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["checks"]["kafka"]["state"], "fail")
        self.assertFalse(report["checks"]["kafka"]["critical"])

    def test_report_never_contains_exception_text(self):
        with _healthy(), mock.patch(
            "apps.core.health.check_database",
            side_effect=OperationalError("password=hunter2 host=db.internal"),
        ):
            report = monitoring.collect()
        raw = json.dumps(report)
        self.assertNotIn("hunter2", raw)
        self.assertNotIn("db.internal", raw)


class CheckFunctionTests(TestCase):
    def test_celery_workers_present(self):
        with mock.patch("config.celery.app") as fake_app:
            fake_app.control.inspect.return_value.ping.return_value = {"w1": {}, "w2": {}}
            self.assertEqual(monitoring.check_celery_workers(), {"workers": 2})

    def test_celery_no_workers_raises(self):
        with mock.patch("config.celery.app") as fake_app:
            fake_app.control.inspect.return_value.ping.return_value = None
            with self.assertRaises(ThresholdExceeded):
                monitoring.check_celery_workers()

    def test_outbox_healthy(self):
        detail = monitoring.check_outbox()
        self.assertEqual(detail["pending"], 0)
        self.assertEqual(detail["dead"], 0)

    @override_settings(MONITOR_OUTBOX_MAX_PENDING=1)
    def test_outbox_pending_over_limit(self):
        _outbox()
        _outbox()
        with self.assertRaises(ThresholdExceeded) as ctx:
            monitoring.check_outbox()
        self.assertEqual(ctx.exception.detail["pending"], 2)

    def test_outbox_dead_events_flagged(self):
        _outbox(OutboxEvent.STATUS_DEAD)
        with self.assertRaises(ThresholdExceeded) as ctx:
            monitoring.check_outbox()
        self.assertEqual(ctx.exception.detail["dead"], 1)

    @override_settings(MONITOR_OUTBOX_MAX_AGE_SECONDS=60)
    def test_outbox_old_pending_event_flagged(self):
        event = _outbox()
        OutboxEvent.objects.filter(pk=event.pk).update(
            created_at=timezone.now() - timedelta(hours=1)
        )
        with self.assertRaises(ThresholdExceeded) as ctx:
            monitoring.check_outbox()
        self.assertGreaterEqual(ctx.exception.detail["oldest_pending_age_seconds"], 3600)

    def test_dead_letters_none_is_ok(self):
        self.assertEqual(
            monitoring.check_dead_letters(), {"dead_events": 0, "failed_tasks": 0}
        )

    def test_dead_letters_dead_event_flagged(self):
        FailedEvent.objects.create(
            event_key="k1", topic="booking.created", payload={}, status=FailedEvent.STATUS_DEAD
        )
        with self.assertRaises(ThresholdExceeded) as ctx:
            monitoring.check_dead_letters()
        self.assertEqual(ctx.exception.detail["dead_events"], 1)

    def test_dead_letters_failed_task_flagged(self):
        with mock.patch("apps.kafka_events.models.FailedTask.objects") as fake_objects:
            fake_objects.filter.return_value.count.return_value = 1
            with self.assertRaises(ThresholdExceeded) as ctx:
                monitoring.check_dead_letters()
        self.assertEqual(ctx.exception.detail["failed_tasks"], 1)


@override_settings(MONITORING_TOKEN="test-token-value")
class DependenciesViewTests(TestCase):
    URL = "/health/dependencies/"

    def _report(self, status):
        return {"status": status, "checked_at": "now", "checks": {}}

    @override_settings(MONITORING_TOKEN="")
    def test_disabled_without_token_setting(self):
        self.assertEqual(self.client.get(self.URL).status_code, 404)

    def test_missing_token_is_forbidden(self):
        self.assertEqual(self.client.get(self.URL).status_code, 403)

    def test_wrong_token_is_forbidden(self):
        response = self.client.get(self.URL, HTTP_X_MONITORING_TOKEN="nope")
        self.assertEqual(response.status_code, 403)

    def test_ok_report_gives_200(self):
        with mock.patch("apps.core.views.collect", return_value=self._report("ok")):
            response = self.client.get(self.URL, HTTP_X_MONITORING_TOKEN="test-token-value")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_degraded_report_still_gives_200(self):
        with mock.patch("apps.core.views.collect", return_value=self._report("degraded")):
            response = self.client.get(self.URL, HTTP_X_MONITORING_TOKEN="test-token-value")
        self.assertEqual(response.status_code, 200)

    def test_down_report_gives_503(self):
        with mock.patch("apps.core.views.collect", return_value=self._report("down")):
            response = self.client.get(self.URL, HTTP_X_MONITORING_TOKEN="test-token-value")
        self.assertEqual(response.status_code, 503)

    def test_post_is_rejected(self):
        response = self.client.post(self.URL, HTTP_X_MONITORING_TOKEN="test-token-value")
        self.assertEqual(response.status_code, 405)


class MonitorTaskTests(TestCase):
    def setUp(self):
        cache.delete(tasks.STATE_KEY)
        tasks._last_status = None

    def _report(self, status, failing=()):
        checks = {name: {"state": "fail"} for name in failing}
        checks["database"] = {"state": "ok"}
        return {"status": status, "checks": checks}

    def test_alerts_once_on_transition_to_degraded(self):
        with mock.patch(
            "apps.core.tasks.collect", return_value=self._report("degraded", ["kafka"])
        ):
            with self.assertLogs("travelx.monitoring", level="ERROR") as logs:
                self.assertEqual(tasks.monitor_dependencies(), "degraded")
            self.assertIn("kafka", logs.output[0])
            with self.assertNoLogs("travelx.monitoring", level="ERROR"):
                tasks.monitor_dependencies()

    def test_logs_recovery(self):
        with mock.patch(
            "apps.core.tasks.collect", return_value=self._report("down", ["database"])
        ):
            with self.assertLogs("travelx.monitoring", level="ERROR"):
                tasks.monitor_dependencies()
        with mock.patch("apps.core.tasks.collect", return_value=self._report("ok")):
            with self.assertLogs("travelx.monitoring", level="WARNING") as logs:
                tasks.monitor_dependencies()
        self.assertIn("recovered", logs.output[0])

    def test_no_alert_when_healthy_from_the_start(self):
        with mock.patch("apps.core.tasks.collect", return_value=self._report("ok")):
            with self.assertNoLogs("travelx.monitoring", level="WARNING"):
                self.assertEqual(tasks.monitor_dependencies(), "ok")


class CheckDependenciesCommandTests(TestCase):
    def _run(self, status, *args):
        report = {
            "status": status,
            "checked_at": "now",
            "checks": {"kafka": {"state": "ok", "latency_ms": 1.0, "critical": False}},
        }
        out = StringIO()
        with mock.patch(
            "apps.core.management.commands.check_dependencies.collect", return_value=report
        ):
            call_command("check_dependencies", *args, stdout=out)
        return out.getvalue()

    def test_json_output(self):
        output = self._run("ok", "--json")
        self.assertEqual(json.loads(output)["status"], "ok")

    def test_down_exits_with_code_2(self):
        with self.assertRaises(SystemExit) as ctx:
            self._run("down")
        self.assertEqual(ctx.exception.code, 2)

    def test_degraded_exits_zero_by_default(self):
        self.assertIn("degraded", self._run("degraded"))

    def test_degraded_with_strict_exits_with_code_1(self):
        with self.assertRaises(SystemExit) as ctx:
            self._run("degraded", "--strict")
        self.assertEqual(ctx.exception.code, 1)