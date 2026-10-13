import hmac

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from apps.core.health import DEFAULT_READINESS_CHECKS, run_checks
from apps.core.metrics import render_metrics
from apps.core.monitoring import STATUS_DOWN, collect


@never_cache
@require_safe
def liveness(request):
    """Process is up and can answer HTTP. Deliberately touches NO dependency,
    so a database outage never makes an orchestrator restart a healthy process."""
    return JsonResponse({"status": "ok"})


@never_cache
@require_safe
def readiness(request):
    """Ready to receive traffic: required dependencies respond. 200 or 503."""
    names = getattr(settings, "HEALTH_READINESS_CHECKS", DEFAULT_READINESS_CHECKS)
    results = run_checks(names)
    healthy = all(state == "ok" for state in results.values())
    return JsonResponse(
        {"status": "ok" if healthy else "unavailable", "checks": results},
        status=200 if healthy else 503,
    )


@never_cache
@require_safe
def dependencies(request):
    """Detailed dependency report (H04). Disabled (404) unless MONITORING_TOKEN
    is set; requires header `X-Monitoring-Token`. 503 only when status is down."""
    token = getattr(settings, "MONITORING_TOKEN", "")
    if not token:
        raise Http404
    supplied = request.headers.get("X-Monitoring-Token", "")
    if not hmac.compare_digest(supplied.encode(), token.encode()):
        return JsonResponse({"detail": "forbidden"}, status=403)
    report = collect()
    return JsonResponse(report, status=503 if report["status"] == STATUS_DOWN else 200)


@never_cache
@require_safe
def metrics(request):
    """Prometheus scrape endpoint (H05). Disabled (404) unless METRICS_TOKEN is
    set; requires `Authorization: Bearer <token>` (what Prometheus sends)."""
    token = getattr(settings, "METRICS_TOKEN", "")
    if not token:
        raise Http404
    header = request.headers.get("Authorization", "")
    supplied = header[len("Bearer "):] if header.startswith("Bearer ") else ""
    if not hmac.compare_digest(supplied.encode(), token.encode()):
        return HttpResponse("forbidden", status=403, content_type="text/plain")
    body, content_type = render_metrics()
    return HttpResponse(body, content_type=content_type)