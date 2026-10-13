"""Structured logging helpers and request correlation IDs (H01).

Standard library only: no new dependency. Nothing here imports Django
models, so it is safe to import from config/celery.py.
"""
import contextvars
import json
import logging
import re
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Correlation ID storage (one value per request / per Celery task execution)
# ---------------------------------------------------------------------------
_request_id = contextvars.ContextVar("travelx_request_id", default=None)


def get_request_id():
    return _request_id.get()


def set_request_id(value):
    """Set the current correlation ID. Returns a token for reset_request_id()."""
    return _request_id.set(value)


def reset_request_id(token):
    try:
        _request_id.reset(token)
    except (ValueError, LookupError):
        # Token created in a different context: fall back to clearing.
        _request_id.set(None)


# ---------------------------------------------------------------------------
# Logging filter + formatters
# ---------------------------------------------------------------------------
class RequestIDFilter(logging.Filter):
    """Attach the current correlation ID to every record ('-' if none)."""

    def filter(self, record):
        record.request_id = get_request_id() or "-"
        return True


# Keys whose values must never reach the logs.
_SENSITIVE_KEY = re.compile(
    r"password|passwd|secret|token|authorization|api[_-]?key|cookie|card|cvv|otp|signature",
    re.IGNORECASE,
)
REDACTED = "[REDACTED]"

# Attributes every LogRecord has: anything else came from `extra=`.
_RESERVED = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "request_id"}


def redact(key, value):
    """Redact by key name, recursing into dicts and lists."""
    if _SENSITIVE_KEY.search(str(key)):
        return REDACTED
    if isinstance(value, dict):
        return {k: redact(k, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(key, v) if isinstance(v, dict) else v for v in value]
    return value


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Extra fields are included, sensitive keys redacted."""

    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or get_request_id(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = redact(key, value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# Celery propagation (HTTP request id -> task, via message headers)
# ---------------------------------------------------------------------------
_task_tokens = {}
_signals_connected = False


def inject_request_id(headers=None, **kwargs):
    """before_task_publish: copy the current correlation ID into task headers."""
    rid = get_request_id()
    if rid and headers is not None:
        headers.setdefault("request_id", rid)


def bind_request_id(task=None, task_id=None, **kwargs):
    """task_prerun: restore the publisher's ID, or fall back to the task id."""
    rid = getattr(getattr(task, "request", None), "request_id", None)
    rid = rid or get_request_id() or f"task-{task_id}"
    _task_tokens[task_id] = set_request_id(rid)


def unbind_request_id(task_id=None, **kwargs):
    """task_postrun: always restore the previous value."""
    token = _task_tokens.pop(task_id, None)
    if token is not None:
        reset_request_id(token)


def connect_celery_signals():
    """Idempotent. Called from config/celery.py."""
    global _signals_connected
    if _signals_connected:
        return
    from celery.signals import before_task_publish, task_postrun, task_prerun

    before_task_publish.connect(inject_request_id, weak=False)
    task_prerun.connect(bind_request_id, weak=False)
    task_postrun.connect(unbind_request_id, weak=False)
    _signals_connected = True