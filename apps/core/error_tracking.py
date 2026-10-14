"""Exception tracking via Sentry (H03).

Design rules:
- Entirely optional: no DSN -> nothing is initialised, nothing is sent.
- No PII by default: no cookies, headers with credentials, query strings,
  request bodies, user identity or local variables leave the process.
- Events are tagged with the H01 correlation id so an alert links to logs.
- sentry_sdk is imported lazily, so the app still boots if it is missing.
"""
import logging

from apps.core.logging_utils import REDACTED, get_request_id, redact

logger = logging.getLogger("travelx.error_tracking")

# Loggers whose ERROR records must NOT become Sentry events:
# - travelx.request: the Django integration already captures the exception
#   itself (would be a duplicate).
# - travelx.health: readiness failures are expected during dependency outages
#   and probes run every few seconds (alerting for that belongs to H04).
IGNORED_LOGGERS = ("travelx.request", "travelx.health")


def scrub_event(event, hint=None):
    """before_send hook: add the correlation id and strip sensitive data."""
    request_id = get_request_id()
    if request_id:
        tags = event.get("tags")
        if isinstance(tags, dict):
            tags["request_id"] = request_id
        else:
            event["tags"] = {"request_id": request_id}

    request = event.get("request")
    if isinstance(request, dict):
        for key in ("query_string", "cookies", "data"):
            request.pop(key, None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {k: redact(k, v) for k, v in headers.items()}

    extra = event.get("extra")
    if isinstance(extra, dict):
        event["extra"] = {k: redact(k, v) for k, v in extra.items()}

    event.pop("user", None)
    return event


def init_sentry(dsn, environment="development", release=None, traces_sample_rate=0.0):
    """Initialise Sentry. Returns True if initialised, False otherwise."""
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.django import DjangoIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration, ignore_logger
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; tracking disabled")
        return False

    for name in IGNORED_LOGGERS:
        ignore_logger(name)

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            # INFO+ become breadcrumbs, ERROR+ (logger.exception) become events.
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        traces_sample_rate=traces_sample_rate,
        before_send=scrub_event,
    )
    return True