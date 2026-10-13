"""Dependency monitoring (H04).

Builds a detailed status report for Postgres, Redis (cache + Celery broker),
Kafka, Celery workers and the app-level queues (outbox backlog, dead letters).

Rules:
- Exception text is logged at WARNING (breadcrumb only) but NEVER put in the
  report, so no hostnames or credentials leak (checklist B10).
- Critical dependencies (database, cache, broker) failing => "down".
  Anything else failing => "degraded" (requests still work: the outbox keeps
  events when Kafka is unavailable, G08).
"""
import logging
import time
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.utils import timezone

from apps.core import flow_health, health


logger = logging.getLogger("travelx.monitoring")

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_DOWN = "down"

CHECK_TIMEOUT_SECONDS = 2


class ThresholdExceeded(Exception):
    """A dependency answered, but an operational threshold is breached.

    `reason` and `detail` are built by this module only (counts and static
    text), so they are safe to expose in the report.
    """

    def __init__(self, reason, detail=None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def check_celery_workers():
    from config.celery import app as celery_app

    replies = celery_app.control.inspect(timeout=CHECK_TIMEOUT_SECONDS).ping()
    if not replies:
        raise ThresholdExceeded("no Celery worker answered", {"workers": 0})
    return {"workers": len(replies)}


def check_outbox():
    from django.db.models import Min

    from apps.kafka_events.models import OutboxEvent

    max_pending = getattr(settings, "MONITOR_OUTBOX_MAX_PENDING", 100)
    max_age = getattr(settings, "MONITOR_OUTBOX_MAX_AGE_SECONDS", 300)

    pending_qs = OutboxEvent.objects.filter(status=OutboxEvent.STATUS_PENDING)
    pending = pending_qs.count()
    dead = OutboxEvent.objects.filter(status=OutboxEvent.STATUS_DEAD).count()
    oldest = pending_qs.aggregate(oldest=Min("created_at"))["oldest"]
    age = int((timezone.now() - oldest).total_seconds()) if oldest else 0

    detail = {"pending": pending, "dead": dead, "oldest_pending_age_seconds": age}
    problems = []
    if pending > max_pending:
        problems.append(f"{pending} pending events (limit {max_pending})")
    if age > max_age:
        problems.append(f"oldest pending event is {age}s old (limit {max_age}s)")
    if dead > 0:
        problems.append(f"{dead} dead outbox events need replay")
    if problems:
        raise ThresholdExceeded("; ".join(problems), detail)
    return detail


def check_dead_letters():
    from apps.kafka_events.models import FailedEvent, FailedTask

    limit = getattr(settings, "MONITOR_DEAD_LETTER_MAX", 0)
    dead_events = FailedEvent.objects.filter(status=FailedEvent.STATUS_DEAD).count()
    failed_tasks = FailedTask.objects.filter(status=FailedTask.STATUS_FAILED).count()

    detail = {"dead_events": dead_events, "failed_tasks": failed_tasks}
    if dead_events + failed_tasks > limit:
        raise ThresholdExceeded(
            f"{dead_events} dead events and {failed_tasks} failed tasks await recovery",
            detail,
            
        )
    return detail


def _run(name, check, critical):
    started = time.monotonic()
    entry = {"critical": critical}
    try:
        detail = check()
        entry["state"] = "ok"
        if detail:
            entry["detail"] = detail
    except ThresholdExceeded as exc:
        entry["state"] = "fail"
        entry["reason"] = exc.reason
        if exc.detail:
            entry["detail"] = exc.detail
    except Exception:
        # Details go to the logs only, never into the report.
        logger.warning("dependency check failed", exc_info=True, extra={"check": name})
        entry["state"] = "fail"
    entry["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
    return entry


def collect():
    """Run every check and return the full report."""
    checks = [
        ("database", health.check_database, True),
        ("cache", health.check_cache, True),
        ("broker", health.check_broker, True),
        ("kafka", health.check_kafka, False),
        ("celery_workers", check_celery_workers, False),
        ("outbox", check_outbox, False),
        ("dead_letters", check_dead_letters, False),
        ("flows", flow_health.check_flow_health, False),
    ]
    results = {name: _run(name, fn, critical) for name, fn, critical in checks}

    failed = [r for r in results.values() if r["state"] != "ok"]
    if any(r["critical"] for r in failed):
        status = STATUS_DOWN
    elif failed:
        status = STATUS_DEGRADED
    else:
        status = STATUS_OK

    return {
        "status": status,
        "checked_at": datetime.now(dt_timezone.utc).isoformat(),
        "checks": results,
    }