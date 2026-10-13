"""Application metrics in Prometheus format (H05).

Two kinds of metrics:
1. Request metrics (counter + latency histogram), recorded by
   MetricsMiddleware in the process that serves the request.
2. Queue/backlog gauges computed from the database at scrape time (outbox,
   consumer dead letters, failed tasks). These are identical no matter which
   process answers the scrape.

Labels never contain raw paths, user data or ids: only the URL ROUTE TEMPLATE
(e.g. "api/v1/bookings/<uuid:pk>/"), so cardinality stays bounded.

Gunicorn with several workers: set PROMETHEUS_MULTIPROC_DIR (an empty,
writable directory, cleaned at every start) BEFORE the processes start, or
request counters will be per-process and wrong.
"""
import logging
import os

from django.utils import timezone
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)
from prometheus_client.core import GaugeMetricFamily
from apps.core.flow_health import FlowHealthCollector
logger = logging.getLogger("travelx.metrics")

HTTP_REQUESTS = Counter(
    "travelx_http_requests_total",
    "HTTP requests handled, by method, route template and status code.",
    ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "travelx_http_request_duration_seconds",
    "HTTP request latency in seconds, by method and route template.",
    ["method", "route"],
    buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


class BusinessCollector:
    """DB-derived gauges, evaluated on each scrape.

    If the database is unreachable the scrape still succeeds and
    travelx_business_metrics_up is 0, so a DB outage never blinds the rest.
    """

    def describe(self):
        # Empty on purpose: stops the registry from calling collect() (and
        # therefore the database) when this collector is registered.
        return []

    def _fetch(self):
        from django.db.models import Count, Min

        from apps.kafka_events.models import FailedEvent, FailedTask, OutboxEvent

        outbox = dict(
            OutboxEvent.objects.filter(
                status__in=[OutboxEvent.STATUS_PENDING, OutboxEvent.STATUS_DEAD]
            )
            .values_list("status")
            .annotate(n=Count("id"))
        )
        oldest = OutboxEvent.objects.filter(
            status=OutboxEvent.STATUS_PENDING
        ).aggregate(oldest=Min("created_at"))["oldest"]
        failed_events = dict(
            FailedEvent.objects.filter(
                status__in=[FailedEvent.STATUS_RETRYING, FailedEvent.STATUS_DEAD]
            )
            .values_list("status")
            .annotate(n=Count("id"))
        )
        failed_tasks = FailedTask.objects.filter(status=FailedTask.STATUS_FAILED).count()
        age = int((timezone.now() - oldest).total_seconds()) if oldest else 0
        return {
            "outbox": outbox,
            "oldest_pending_age": age,
            "failed_events": failed_events,
            "failed_tasks": failed_tasks,
            "keys": {
                "pending": OutboxEvent.STATUS_PENDING,
                "dead": OutboxEvent.STATUS_DEAD,
                "retrying": FailedEvent.STATUS_RETRYING,
                "fe_dead": FailedEvent.STATUS_DEAD,
            },
        }

    def collect(self):
        up = GaugeMetricFamily(
            "travelx_business_metrics_up",
            "1 if the database-derived metrics were collected on this scrape.",
        )
        try:
            data = self._fetch()
        except Exception:
            logger.warning("business metrics collection failed", exc_info=True)
            up.add_metric([], 0)
            yield up
            return

        up.add_metric([], 1)
        yield up
        keys = data["keys"]

        outbox = GaugeMetricFamily(
            "travelx_outbox_events", "Outbox events by status.", labels=["status"]
        )
        outbox.add_metric(["pending"], data["outbox"].get(keys["pending"], 0))
        outbox.add_metric(["dead"], data["outbox"].get(keys["dead"], 0))
        yield outbox

        age = GaugeMetricFamily(
            "travelx_outbox_oldest_pending_age_seconds",
            "Age of the oldest pending outbox event (0 if none).",
        )
        age.add_metric([], data["oldest_pending_age"])
        yield age

        failed_events = GaugeMetricFamily(
            "travelx_failed_events",
            "Kafka consumer failure records by status.",
            labels=["status"],
        )
        failed_events.add_metric(["retrying"], data["failed_events"].get(keys["retrying"], 0))
        failed_events.add_metric(["dead"], data["failed_events"].get(keys["fe_dead"], 0))
        yield failed_events

        failed_tasks = GaugeMetricFamily(
            "travelx_failed_tasks",
            "Celery tasks that failed permanently and await recovery.",
        )
        failed_tasks.add_metric([], data["failed_tasks"])
        yield failed_tasks


def _multiprocess_enabled():
    return bool(os.environ.get("PROMETHEUS_MULTIPROC_DIR"))


if not _multiprocess_enabled():
    for _collector in (BusinessCollector(), FlowHealthCollector()):
        try:
            REGISTRY.register(_collector)
        except ValueError:  # already registered (module reloaded)
            pass


def build_registry():
    """Registry to render. Single process: the default registry, which already
    carries the standard process/python collectors plus the business and flow
    collectors registered at import. Multiprocess: aggregate the per-process
    files into a fresh registry and add the scrape-time collectors."""
    if not _multiprocess_enabled():
        return REGISTRY
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    registry.register(BusinessCollector())
    registry.register(FlowHealthCollector())
    return registry

def render_metrics():
    return generate_latest(build_registry()), CONTENT_TYPE_LATEST