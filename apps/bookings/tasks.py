"""
Email/notification tasks (checklists G02 + G03).

G03 behaviour:
- Bounded retries: transient failures (network/SMTP errors, database
  connection errors, soft time-limit hits) are retried up to 5 times with
  exponential backoff (1s, 2s, 4s ... capped at 300s) plus jitter. After
  that the task fails and EmailTask.on_failure logs it.
- Timeouts: soft limit 30s (raises SoftTimeLimitExceeded inside the task,
  which is retried), hard limit 60s. Celery enforces these only with the
  default "prefork" pool (Linux/Docker). On Windows with --pool=solo they are
  NOT enforced; EMAIL_TIMEOUT in settings.py is the socket-level protection
  there.
- Idempotency: each (booking, kind) email is recorded in EmailNotification.
  The row is locked (select_for_update) while sending, so a duplicate task
  waits and then sees SENT and skips. A failed send rolls the row back, so a
  retry can send it. This is duplicate *suppression*, not exactly-once: if a
  worker dies after the SMTP server accepted the message but before the
  database commit, the retry can send it a second time.
- acks_late: a task is acknowledged after it finishes, so a worker crash
  mid-task causes redelivery rather than silent loss (this is why the
  idempotency check above matters).

Not handled here: dead-letter storage / manual replay of permanently failed
emails (G10). Permanent SMTP errors such as bad credentials are also retried
(they subclass OSError) before failing.
"""
import logging

from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import OperationalError, transaction
from django.utils import timezone

from apps.bookings.models import Booking, EmailNotification

logger = logging.getLogger(__name__)

RETRYABLE_EXCEPTIONS = (OSError, OperationalError, SoftTimeLimitExceeded)

# F-005: Celery autodiscovery imports only this module (tasks.py), so the
# expiry sweep's module must be imported from here for its @shared_task to
# register on workers (it stays DORMANT — registered, never scheduled).
# Imported at the bottom of this module to keep import order obvious; see
# the import statement at the end of the file.


class ReceiptNotYetVisible(OSError):
    """
    The payment is recorded as SUCCESS but the booking is not PAID yet.

    The payment.success handler queues the receipt task INSIDE the transaction
    that marks the booking PAID, so a fast worker can read the booking before
    that transaction commits. Subclassing OSError keeps this inside
    RETRYABLE_EXCEPTIONS, so Celery retries with its normal backoff instead of
    the receipt being silently skipped.
    """


def _payment_is_success(booking):
    from apps.payments.models import Payment

    return Payment.objects.filter(booking=booking, status="SUCCESS").exists()


class EmailTask(Task):
    """Base class: log a permanent failure (after retries are exhausted)."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(
            "Email task %s (id=%s) failed permanently for args=%s: %r",
            self.name, task_id, args, exc,
        )
        # G10: keep a replayable record. Bookkeeping must never hide or replace
        # the original failure, so any error here is logged and swallowed.
        try:
            from apps.kafka_events.models import FailedTask

            FailedTask.objects.update_or_create(
                task_id=task_id,
                defaults={
                    "task_name": self.name,
                    "args": list(args or []),
                    "kwargs": dict(kwargs or {}),
                    "error": repr(exc),
                    "status": FailedTask.STATUS_FAILED,
                },
            )
        except Exception:
            logger.exception("Could not record failed task %s (id=%s)", self.name, task_id)


EMAIL_TASK_OPTIONS = dict(
    base=EmailTask,
    autoretry_for=RETRYABLE_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
    soft_time_limit=30,
    time_limit=60,
    acks_late=True,
)


def _get_booking(booking_id):
    try:
        return Booking.objects.select_related("user").get(id=booking_id)
    except (Booking.DoesNotExist, ValueError, TypeError, ValidationError):
        return None


def _describe_items(booking):
    lines = []
    for item in booking.items.all():
        line = f"- {item.get_item_type_display()}: {item.item_name} (qty {item.quantity}"
        if item.nights:
            line += f", {item.nights} night(s)"
        line += f"), price at booking: INR {item.price_at_booking}"
        lines.append(line)
    return "\n".join(lines) if lines else "- (no items recorded)"


def _short_id(booking):
    return str(booking.id)[:8]


def _guest_name(user):
    return user.get_full_name() or user.username


def _send_once(booking, kind, subject, message):
    """
    Send the email at most once per (booking, kind), suppressing duplicates.

    Everything happens in one transaction holding a row lock. If send_mail
    raises, the transaction rolls back (nothing is recorded as sent) and the
    exception propagates so Celery can retry.
    """
    with transaction.atomic():
        record, _created = EmailNotification.objects.select_for_update().get_or_create(
            booking=booking, kind=kind
        )
        if record.status == EmailNotification.STATUS_SENT:
            logger.info("%s email for booking %s already sent; skipping", kind, booking.id)
            return "skipped:already-sent"

        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [booking.user.email],
            fail_silently=False,
        )
        record.status = EmailNotification.STATUS_SENT
        record.sent_at = timezone.now()
        record.save(update_fields=["status", "sent_at"])

    logger.info("%s email sent for booking %s", kind, booking.id)
    return "sent"


@shared_task(**EMAIL_TASK_OPTIONS)
def send_booking_confirmation(booking_id):
    booking = _get_booking(booking_id)
    if booking is None:
        logger.error("Confirmation email skipped: booking %r not found", booking_id)
        return "skipped:booking-not-found"

    if booking.status == "CANCELLED":
        logger.info("Confirmation email skipped: booking %s is cancelled", booking.id)
        return "skipped:cancelled"

    if not booking.user.email:
        logger.warning("Confirmation email skipped: user of booking %s has no email", booking.id)
        return "skipped:no-email"

    subject = f"TravelX booking received - #{_short_id(booking)}"
    message = (
        f"Hello {_guest_name(booking.user)},\n\n"
        f"We have received your booking #{_short_id(booking)}.\n\n"
        f"Status: {booking.status}\n"
        f"Check-in: {booking.check_in}\n"
        f"Check-out: {booking.check_out}\n\n"
        f"Items:\n{_describe_items(booking)}\n\n"
        f"Total amount: INR {booking.total_amount}\n\n"
        f"Thank you for choosing TravelX."
    )
    return _send_once(booking, EmailNotification.KIND_CONFIRMATION, subject, message)


@shared_task(**EMAIL_TASK_OPTIONS)
def send_payment_receipt(booking_id):
    booking = _get_booking(booking_id)
    if booking is None:
        logger.error("Receipt email skipped: booking %r not found", booking_id)
        return "skipped:booking-not-found"

    if booking.status != "PAID":
        if booking.status in ("PENDING", "CONFIRMED") and _payment_is_success(booking):
            # Not a permanent skip: the PAID transition is committing. Retry.
            raise ReceiptNotYetVisible(
                f"booking {booking.id} is {booking.status} but its payment is SUCCESS"
            )
        logger.warning(
            "Receipt email skipped: booking %s status is %s, not PAID", booking.id, booking.status
        )
        return "skipped:not-paid"

    if not booking.user.email:
        logger.warning("Receipt email skipped: user of booking %s has no email", booking.id)
        return "skipped:no-email"

    subject = f"TravelX payment receipt - #{_short_id(booking)}"
    message = (
        f"Hello {_guest_name(booking.user)},\n\n"
        f"We have received your payment for booking #{_short_id(booking)}.\n\n"
        f"Amount paid: INR {booking.total_amount}\n"
        f"Check-in: {booking.check_in}\n"
        f"Check-out: {booking.check_out}\n\n"
        f"Items:\n{_describe_items(booking)}\n\n"
        f"Thank you for choosing TravelX."
    )
    return _send_once(booking, EmailNotification.KIND_RECEIPT, subject, message)

# F-005 (see the note near RETRYABLE_EXCEPTIONS): registers the dormant
# expiry sweep with Celery via autodiscovery of this module. The sweep's own
# imports are lazy (inside its functions), so this cannot create an import
# cycle.
from apps.bookings import tasks_expiry  # noqa: E402,F401  (registration import)
