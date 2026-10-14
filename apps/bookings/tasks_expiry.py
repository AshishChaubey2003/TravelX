"""
F-005 — expiry sweep for stale PENDING bookings (DORMANT: registered as a
Celery task but deliberately NOT in any beat schedule; enabling it is a
separate, explicit approval).

Business rule (signed off in docs/audit/PROPOSED_DIFFS_V2.md §F-005):
a booking expires when ALL of the following hold —
  1. status == 'PENDING',
  2. created_at is older than settings.BOOKING_PENDING_EXPIRY_MINUTES
     (default 30, env-overridable), and
  3. NO Payment row exists for it. ANY Payment row — PENDING, SUCCESS,
     FAILED, REFUND_PENDING, REFUNDED — exempts the booking from this sweep,
     because its payment outcome is uncertain without asking the gateway.
     Those bookings stay visible via the travelx_bookings_pending_stale /
     travelx_payments_pending_stale gauges (apps/core/flow_health.py) and are
     reconciled only by the (deferred, design-only) gateway-confirmed
     secondary sweep. That operational decision remains OPEN.

Expiry effect: status -> CANCELLED and BookingService.release_inventory, in
ONE transaction under the booking row lock — the same single-transition
discipline every other releaser follows, so inventory is released at most
once per booking across all paths (user cancel, payment-failed consumer,
refund webhook, this sweep).

Locking correctness: the candidate query below takes NO locks and is only a
pre-filter. Every condition is RE-CHECKED inside the per-booking transaction
while holding select_for_update on the booking row:
  - the locked get() re-asserts status='PENDING' (a booking paid or cancelled
    meanwhile raises DoesNotExist -> skipped);
  - created_at is re-checked under the lock;
  - Payment existence is RE-QUERIED under the lock (a Payment committed
    between the candidate query and the lock — e.g. RazorpayService
    .create_order, which creates the Payment under this same booking lock —
    is seen, and the booking is skipped). The pre-filter alone would race
    checkout; the in-lock recheck is the actual gate.
NOTE (honesty): on SQLite select_for_update is a no-op, so tests prove the
recheck logic, never the lock serialisation — that needs PostgreSQL.

Manual invocation (development / operations):
    python manage.py expire_pending_bookings [--minutes N]
or from code/tests: expire_stale_pending_bookings() (synchronous call).
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def _cutoff(minutes=None):
    if minutes is None:
        minutes = getattr(settings, 'BOOKING_PENDING_EXPIRY_MINUTES', 30)
    return timezone.now() - timedelta(minutes=minutes)


def _expire_one_booking(booking_id, cutoff):
    """
    Expire a single booking, re-checking every condition under the row lock.

    Returns one of: 'expired', 'skipped:not-pending', 'skipped:too-recent',
    'skipped:has-payment'. Exposed separately from the sweep so tests can
    drive the between-select-and-lock race deterministically.
    """
    from apps.bookings.models import Booking
    from apps.bookings.services import BookingService
    from apps.payments.models import Payment

    with transaction.atomic():
        try:
            booking = Booking.objects.select_for_update().get(
                pk=booking_id, status='PENDING',
            )
        except Booking.DoesNotExist:
            # Paid, cancelled, or gone since the candidate query: the status
            # predicate inside the locked get IS the recheck.
            return 'skipped:not-pending'

        if booking.created_at > cutoff:
            return 'skipped:too-recent'

        # MUST stay inside this transaction, after the lock (F-005 review,
        # M13 §2.4): a Payment committed since the candidate query exempts
        # the booking. create_order writes the Payment under this same
        # booking lock, so on PostgreSQL the two serialise.
        if Payment.objects.filter(booking=booking).exists():
            return 'skipped:has-payment'

        BookingService.release_inventory(booking)
        booking.status = 'CANCELLED'
        booking.save(update_fields=['status'])

    logger.info('Expired stale PENDING booking %s (created %s)',
                booking_id, booking.created_at.isoformat())
    return 'expired'


@shared_task
def expire_stale_pending_bookings(minutes=None, batch_size=500):
    """
    One sweep pass. Safe to re-run (idempotent: an already-cancelled booking
    no longer matches the locked PENDING get). Returns a summary dict.
    """
    from apps.bookings.models import Booking

    cutoff = _cutoff(minutes)
    candidate_ids = list(
        Booking.objects
        .filter(status='PENDING', created_at__lt=cutoff, payment__isnull=True)
        .order_by('created_at')
        .values_list('pk', flat=True)[:batch_size]
    )

    summary = {'expired': 0, 'skipped': 0, 'failed': 0}
    for booking_id in candidate_ids:
        try:
            outcome = _expire_one_booking(booking_id, cutoff)
        except Exception:  # noqa: BLE001 — one broken booking must not abort the pass
            # The per-booking transaction has rolled back: the booking stays
            # PENDING and its inventory untouched (cancel + release are
            # atomic). Logged loudly, counted, sweep continues.
            summary['failed'] += 1
            logger.error('Expiry sweep failed for booking %s; transaction '
                         'rolled back, booking left PENDING', booking_id,
                         exc_info=True)
            continue
        if outcome == 'expired':
            summary['expired'] += 1
        else:
            summary['skipped'] += 1
            logger.info('Expiry sweep skipped booking %s: %s', booking_id, outcome)

    if summary['expired'] or summary['skipped']:
        logger.info('Expiry sweep done: %s', summary)
    return summary
