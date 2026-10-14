"""H01: request-ID middleware.

Accepts a caller-supplied X-Request-ID (only if it looks safe), otherwise
generates one. Binds it to a contextvar for logs, echoes it on the response,
and logs one "request completed" line per request. Query strings are never
logged.
"""
import logging
import re
import time
import uuid

from apps.core.logging_utils import reset_request_id, set_request_id

logger = logging.getLogger("travelx.request")

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get("HTTP_X_REQUEST_ID", "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id
        token = set_request_id(request_id)
        started = time.monotonic()
        try:
            response = self.get_response(request)
            response[REQUEST_ID_HEADER] = request_id
            status_code = response.status_code
            level = logging.ERROR if status_code >= 500 else logging.WARNING if status_code >= 400 else logging.INFO
            logger.log(
                level,
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.path,
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                },
            )
            return response
        finally:
            reset_request_id(token)