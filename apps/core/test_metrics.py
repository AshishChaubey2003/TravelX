import os
import tempfile
import uuid
from datetime import timedelta
from unittest import mock

from django.db.utils import OperationalError
from django.test import TestCase, override_settings
from django.utils import timezone
from prometheus_client import REGISTRY, CollectorRegistry

from apps.core import metrics
from apps.core.metrics import BusinessCollector
from apps.kafka_events.models import FailedEvent, OutboxEvent


def _requests(method, route, status):
    return (
        REGISTRY.get_sample_value(
            "travelx_http_requests_total",
            {"method": method, "route": route, "status": status},
        )
        or 0
    )


def _samples(collector):
    out = {}
    for family in collector.collect():
        for sample in family.samples:
            out[(sample.name, tuple(sorted(sample.labels.items())))] = sample.value
    return out


class MetricsMiddlewareTests(TestCase):
    def test_request_is_counted_by_route_template(self):
        before = _requests("GET", "health/live/", "200")
        self.client.get("/health/live/")
        self.assertEqual(_requests("GET", "health/live/", "200"), before + 1)

    def test_unmatched_path_uses_a_single_label(self):
        before = _requests("GET", "unmatched", "404")
        self.client.get("/h05-no-such-route-aaa/")
        self.client.get("/h05-no-such-route-bbb/")
        self.assertEqual(_requests("GET", "unmatched", "404"), before + 2)

    def test_latency_histogram_is_observed(self):
        labels = {"method": "GET", "route": "health/live/"}
        before = REGISTRY.get_sample_value(
            "travelx_http_request_duration_seconds_count", labels
        ) or 0
        self.client.get("/health/live/")
        after = REGISTRY.get_sample_value(
            "travelx_http_request_duration_seconds_count", labels
        )
        self.assertEqual(after, before + 1)

    def test_unknown_http_method_is_bucketed_as_other(self):
        before = _requests("OTHER", "health/live/", "405")
        self.client.generic("FOO", "/health/live/")
        self.assertEqual(_requests("OTHER", "health/live/", "405"), before + 1)

    @override_settings(METRICS_TOKEN="test-token-value")
    def test_scrapes_are_not_counted(self):
        self.client.get("/metrics", HTTP_AUTHORIZATION="Bearer test-token-value")
        for route in ("^metrics/?$", "unmatched"):
            samples = [
                s
                for family in REGISTRY.collect()
                if family.name == "travelx_http_requests"
                for s in family.samples
                if s.labels.get("route") == route and "metrics" in route
            ]
            self.assertEqual(samples, [])


@override_settings(METRICS_TOKEN="test-token-value")
class MetricsViewTests(TestCase):
    AUTH = {"HTTP_AUTHORIZATION": "Bearer test-token-value"}

    @override_settings(METRICS_TOKEN="")
    def test_disabled_without_token_setting(self):
        self.assertEqual(self.client.get("/metrics").status_code, 404)

    def test_missing_token_is_forbidden(self):
        self.assertEqual(self.client.get("/metrics").status_code, 403)

    def test_wrong_token_is_forbidden(self):
        response = self.client.get("/metrics", HTTP_AUTHORIZATION="Bearer nope")
        self.assertEqual(response.status_code, 403)

    def test_valid_token_returns_prometheus_text(self):
        self.client.get("/health/live/")
        response = self.client.get("/metrics", **self.AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/plain"))
        body = response.content.decode()
        self.assertIn("travelx_http_requests_total", body)
        self.assertIn("travelx_outbox_events", body)
        self.assertNotIn("test-token-value", body)

    def test_works_with_and_without_trailing_slash(self):
        self.assertEqual(self.client.get("/metrics", **self.AUTH).status_code, 200)
        self.assertEqual(self.client.get("/metrics/", **self.AUTH).status_code, 200)

    def test_post_is_rejected(self):
        self.assertEqual(self.client.post("/metrics", **self.AUTH).status_code, 405)


class BusinessCollectorTests(TestCase):
    def _outbox(self, status):
        return OutboxEvent.objects.create(
            event_id=uuid.uuid4(), topic="booking.created", key="k", payload={}, status=status
        )

    def test_describe_is_empty_so_registration_never_hits_the_database(self):
        self.assertEqual(BusinessCollector().describe(), [])

    def test_empty_database_reports_zeros(self):
        samples = _samples(BusinessCollector())
        self.assertEqual(samples[("travelx_business_metrics_up", ())], 1)
        self.assertEqual(samples[("travelx_outbox_events", (("status", "pending"),))], 0)
        self.assertEqual(samples[("travelx_outbox_events", (("status", "dead"),))], 0)
        self.assertEqual(samples[("travelx_outbox_oldest_pending_age_seconds", ())], 0)
        self.assertEqual(samples[("travelx_failed_tasks", ())], 0)

    def test_counts_by_status(self):
        self._outbox(OutboxEvent.STATUS_PENDING)
        self._outbox(OutboxEvent.STATUS_PENDING)
        self._outbox(OutboxEvent.STATUS_DEAD)
        self._outbox(OutboxEvent.STATUS_PUBLISHED)  # must not be counted
        FailedEvent.objects.create(
            event_key="k1", topic="t", payload={}, status=FailedEvent.STATUS_DEAD
        )
        samples = _samples(BusinessCollector())
        self.assertEqual(samples[("travelx_outbox_events", (("status", "pending"),))], 2)
        self.assertEqual(samples[("travelx_outbox_events", (("status", "dead"),))], 1)
        self.assertEqual(samples[("travelx_failed_events", (("status", "dead"),))], 1)
        self.assertEqual(samples[("travelx_failed_events", (("status", "retrying"),))], 0)

    def test_oldest_pending_age(self):
        event = self._outbox(OutboxEvent.STATUS_PENDING)
        OutboxEvent.objects.filter(pk=event.pk).update(
            created_at=timezone.now() - timedelta(hours=1)
        )
        samples = _samples(BusinessCollector())
        self.assertGreaterEqual(
            samples[("travelx_outbox_oldest_pending_age_seconds", ())], 3600
        )

    def test_database_failure_does_not_break_the_scrape(self):
        with mock.patch.object(
            BusinessCollector, "_fetch", side_effect=OperationalError("db down")
        ):
            samples = _samples(BusinessCollector())
        self.assertEqual(samples, {("travelx_business_metrics_up", ()): 0})


class RegistryTests(TestCase):
    def test_single_process_uses_the_default_registry(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)
            self.assertIs(metrics.build_registry(), REGISTRY)

    def test_multiprocess_mode_builds_an_aggregating_registry(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"PROMETHEUS_MULTIPROC_DIR": tmp}
        ):
            registry = metrics.build_registry()
            self.assertIsInstance(registry, CollectorRegistry)
            self.assertIsNot(registry, REGISTRY)
            body, _ = metrics.render_metrics()
        self.assertIn(b"travelx_business_metrics_up", body)