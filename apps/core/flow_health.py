"""Health and failure visibility for the booking and payment flows (H06).

Three pieces:
1. record_flow(): one call per flow outcome. Increments a Prometheus counter
   and writes a structured log line (H01 adds the request_id automatically).
   Failures log at ERROR, so H03 Sentry turns them into events.
2. FlowHealthCollector: DB-derived gauges at scrape time (H05 endpoint):
   bookings/payments by status, stale pending items, and data inconsistencies
   (money and booking status that disagree).
3. check_flow_health(): the same snapshot as an H04 dependency check, so a
   breached threshold goes through the existing state-change alert.

Safety rules:
- record_flow NEVER raises: instrumentation must not break a payment.
- Only an allowlist of fields is logged (booking_id, order_id, reason).
  Signatures, payment ids, emails and amounts cannot be logged by accident.
- `reason` must be a short code ("invalid_signature"), never str(exception).
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from prometheus_client import Counter
from prometheus_client.core import GaugeMetricFamily

logger = logging.getLogger("travelx.flow")

FLOWS = frozenset(
    {"booking_create", "booking_cancel", "payment_order", "payment_verify", "refund"}
)
# success  : the operation did what was asked
# rejected : expected business/user outcome (not found, invalid signature, rule)
# failure  : unexpected error; needs a human
OUTCOMES = frozenset({"success", "rejected", "failure"})
ALLOWED_FIELDS = frozenset({"booking_id", "order_id", "reason"})
_LEVELS = {
    "success": logging.INFO,
    "rejected": logging.WARNING,
    "failure": logging.ERROR,
}

BOOKING_STATUSES = ("PENDING", "CONFIRMED", "PAID", "CANCELLED")
PAYMENT_STATUSES = ("PENDING", "SUCCESS", "FAILED", "REFUNDED")

FLOW_EVENTS = Counter(
    "travelx_flow_events_total",
    "Booking/payment flow outcomes, by flow and outcome.",
    ["flow", "outcome"],
)


def record_flow(flow, outcome, exc_info=False, **fields):
    """Record one flow outcome. Never raises."""
    try:
        if flow not in FLOWS or outcome not in OUTCOMES:
            logger.error("invalid flow event ignored")
            return
        FLOW_EVENTS.labels(flow, outcome).inc()
        extra = {"flow": flow, "outcome": outcome}
        for key, value in fields.items():
            if key in ALLOWED_FIELDS and value is not None:
                extra[key] = str(value)[:200]
        logger.log(
            _LEVELS[outcome], "%s %s", flow, outcome, extra=extra, exc_info=exc_info
        )
    except Exception:
        logger.warning("recording flow event failed", exc_info=True)


def _snapshot():
    from django.db.models import Count

    from apps.bookings.models import Booking
    from apps.payments.models import Payment

    minutes = getattr(settings, "FLOW_PENDING_STALE_MINUTES", 30)
    cutoff = timezone.now() - timedelta(minutes=minutes)

    bookings = dict(
        Booking.objects.order_by().values_list("status").annotate(n=Count("id"))
    )
    payments = dict(
        Payment.objects.order_by().values_list("status").annotate(n=Count("id"))
    )
    return {
        "bookings": bookings,
        "payments": payments,
        "stale_bookings": Booking.objects.filter(
            status="PENDING", created_at__lt=cutoff
        ).count(),
        "stale_payments": Payment.objects.filter(
            status="PENDING", created_at__lt=cutoff
        ).count(),
        # Booking marked PAID but no successful payment behind it.
        "paid_without_payment": Booking.objects.filter(status="PAID")
        .exclude(payment__status="SUCCESS")
        .count(),
        # Money captured but the booking never became PAID.
        # (CANCELLED is excluded: a refunded booking legitimately ends there.)
        "payment_without_paid": Payment.objects.filter(
            status="SUCCESS", booking__status__in=["PENDING", "CONFIRMED"]
        ).count(),
    }


class FlowHealthCollector:
    """Prometheus collector evaluated on every scrape (registered in metrics.py)."""

    def describe(self):
        # Empty on purpose: registration must not query the database.
        return []

    def collect(self):
        up = GaugeMetricFamily(
            "travelx_flow_metrics_up",
            "1 if the booking/payment health gauges were collected on this scrape.",
        )
        try:
            snap = _snapshot()
        except Exception:
            logger.warning("flow health collection failed", exc_info=True)
            up.add_metric([], 0)
            yield up
            return
        up.add_metric([], 1)
        yield up

        bookings = GaugeMetricFamily(
            "travelx_bookings", "Bookings by status.", labels=["status"]
        )
        for status in BOOKING_STATUSES:
            bookings.add_metric([status], snap["bookings"].get(status, 0))
        yield bookings

        payments = GaugeMetricFamily(
            "travelx_payments", "Payments by status.", labels=["status"]
        )
        for status in PAYMENT_STATUSES:
            payments.add_metric([status], snap["payments"].get(status, 0))
        yield payments

        stale_b = GaugeMetricFamily(
            "travelx_bookings_pending_stale",
            "PENDING bookings older than FLOW_PENDING_STALE_MINUTES.",
        )
        stale_b.add_metric([], snap["stale_bookings"])
        yield stale_b

        stale_p = GaugeMetricFamily(
            "travelx_payments_pending_stale",
            "PENDING payments older than FLOW_PENDING_STALE_MINUTES.",
        )
        stale_p.add_metric([], snap["stale_payments"])
        yield stale_p

        bad = GaugeMetricFamily(
            "travelx_flow_inconsistencies",
            "Booking/payment states that contradict each other.",
            labels=["kind"],
        )
        bad.add_metric(["paid_booking_without_successful_payment"], snap["paid_without_payment"])
        bad.add_metric(["successful_payment_booking_not_paid"], snap["payment_without_paid"])
        yield bad


def check_flow_health():
    """H04 dependency check: raises ThresholdExceeded on a breached threshold."""
    from apps.core.monitoring import ThresholdExceeded

    snap = _snapshot()
    max_stale = getattr(settings, "FLOW_MAX_STALE_PENDING", 50)
    max_bad = getattr(settings, "FLOW_MAX_INCONSISTENT", 0)

    inconsistent = snap["paid_without_payment"] + snap["payment_without_paid"]
    detail = {
        "stale_pending_bookings": snap["stale_bookings"],
        "stale_pending_payments": snap["stale_payments"],
        "paid_booking_without_successful_payment": snap["paid_without_payment"],
        "successful_payment_booking_not_paid": snap["payment_without_paid"],
    }
    problems = []
    if snap["stale_bookings"] > max_stale:
        problems.append(f"{snap['stale_bookings']} stale pending bookings (limit {max_stale})")
    if snap["stale_payments"] > max_stale:
        problems.append(f"{snap['stale_payments']} stale pending payments (limit {max_stale})")
    if inconsistent > max_bad:
        problems.append(f"{inconsistent} booking/payment inconsistencies (limit {max_bad})")
    if problems:
        raise ThresholdExceeded("; ".join(problems), detail)
    return detail