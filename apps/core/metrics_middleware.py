"""H05: records request count and latency per route template.

Uses the URL *template* (e.g. api/v1/hotels/<int:pk>/), never the raw path, so
label cardinality stays bounded. A metrics failure never breaks a request.
"""
import logging
import time

from apps.core.metrics import HTTP_LATENCY, HTTP_REQUESTS

logger = logging.getLogger("travelx.metrics")

_KNOWN_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


class MetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/metrics"):
            return self.get_response(request)
        started = time.monotonic()
        response = self.get_response(request)
        try:
            match = getattr(request, "resolver_match", None)
            route = match.route if match is not None and match.route else "unmatched"
            method = request.method if request.method in _KNOWN_METHODS else "OTHER"
            HTTP_REQUESTS.labels(
                method=method, route=route, status=str(response.status_code)
            ).inc()
            HTTP_LATENCY.labels(method=method, route=route).observe(
                time.monotonic() - started
            )
        except Exception:
            logger.exception("metrics recording failed")
        return response