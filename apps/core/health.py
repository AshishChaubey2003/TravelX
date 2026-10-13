"""Dependency checks used by the readiness endpoint (H02).

Rules:
- Every check is isolated: one failing check never hides the others.
- Exception text is logged (with the H01 request id) but NEVER returned to
  the caller, so no hostnames/credentials leak (see checklist B10).
- Every network check has a short timeout so a probe cannot hang.
"""
import logging

from django.conf import settings
from django.core.cache import cache
from django.db import connection

logger = logging.getLogger("travelx.health")

CHECK_TIMEOUT_SECONDS = 2
DEFAULT_READINESS_CHECKS = ["database", "cache"]


def check_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()


def check_cache():
    key = "travelx:health:probe"
    cache.set(key, "1", timeout=10)
    if cache.get(key) != "1":
        raise RuntimeError("cache round-trip failed")


def check_broker():
    """Celery broker (Redis) reachable. Opt-in via HEALTH_READINESS_CHECKS."""
    from kombu import Connection

    conn = Connection(
        settings.CELERY_BROKER_URL, connect_timeout=CHECK_TIMEOUT_SECONDS
    )
    try:
        conn.ensure_connection(max_retries=1, timeout=CHECK_TIMEOUT_SECONDS)
    finally:
        conn.release()


def check_kafka():
    """Kafka metadata reachable. Opt-in via HEALTH_READINESS_CHECKS."""
    from confluent_kafka.admin import AdminClient

    admin = AdminClient({"bootstrap.servers": settings.KAFKA_BROKER})
    admin.list_topics(timeout=CHECK_TIMEOUT_SECONDS)


CHECKS = {
    "database": check_database,
    "cache": check_cache,
    "broker": check_broker,
    "kafka": check_kafka,
}


def run_checks(names):
    """Run the named checks. Returns {name: "ok" | "fail"}."""
    results = {}
    for name in names:
        check = CHECKS.get(name)
        if check is None:
            # A misconfigured name must be visible, not silently ignored.
            logger.error("unknown readiness check", extra={"check": name})
            results[name] = "fail"
            continue
        try:
            check()
            results[name] = "ok"
        except Exception:
            logger.exception("readiness check failed", extra={"check": name})
            results[name] = "fail"
    return results