"""Periodic dependency monitor (H04), run by Celery beat.

Alerts on STATE CHANGES only (ok -> degraded/down, or a change between the
two), so a long outage produces one alert, not one per run. The alert is an
ERROR log on `travelx.monitoring`: it appears in the H01 JSON logs and, when
H03 Sentry is enabled, becomes a Sentry event.
"""
import logging

from celery import shared_task
from django.core.cache import cache

from apps.core.monitoring import STATUS_OK, collect

logger = logging.getLogger("travelx.monitoring")

STATE_KEY = "travelx:monitor:last_status"
_last_status = None  # fallback when the cache itself is down


def _get_state():
    try:
        return cache.get(STATE_KEY)
    except Exception:
        return _last_status


def _set_state(status):
    global _last_status
    _last_status = status
    try:
        cache.set(STATE_KEY, status, None)
    except Exception:
        pass


@shared_task(name="apps.core.tasks.monitor_dependencies", ignore_result=True)
def monitor_dependencies():
    report = collect()
    status = report["status"]
    previous = _get_state()
    _set_state(status)

    failing = sorted(n for n, c in report["checks"].items() if c.get("state") != "ok")
    extra = {"status": status, "previous_status": previous, "failing": failing}

    if status != STATUS_OK and status != previous:
        logger.error("dependency monitor: %s (failing: %s)", status, ", ".join(failing), extra=extra)
    elif status == STATUS_OK and previous not in (None, STATUS_OK):
        logger.warning("dependency monitor: recovered", extra=extra)
    return status