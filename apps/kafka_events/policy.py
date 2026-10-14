"""
Worker safety policy (checklist G11).

Single place that states what background workers (Celery tasks and the Kafka
consumer's handlers) are allowed to do. Changing this file is a deliberate,
reviewable act.
"""

# Every Celery task this project is allowed to register. A test fails if a
# task is registered that is not listed here, so a new task cannot be added
# without someone updating (and therefore reviewing) this list.
ALLOWED_TASK_NAMES = frozenset({
    'config.celery.debug_task',
    'apps.bookings.tasks.send_booking_confirmation',
    'apps.bookings.tasks.send_payment_receipt',
    'apps.core.tasks.monitor_dependencies',   # H04
    # F-005: registered but DORMANT — no beat entry; manual invocation only
    # (manage.py expire_pending_bookings). Scheduling is a separate approval.
    'apps.bookings.tasks_expiry.expire_stale_pending_bookings',
})

# The subset of those tasks that "manage.py recovery replay-tasks" may re-queue
# (G11). Only the two booking email tasks are replayable. Beat-driven and
# diagnostic tasks are deliberately excluded: monitor_dependencies re-runs on
# its own schedule and config.celery.debug_task must never be replayed.
REPLAYABLE_TASK_NAMES = frozenset({
    'apps.bookings.tasks.send_booking_confirmation',
    'apps.bookings.tasks.send_payment_receipt',
})

# Booking status changes that Kafka event handlers may perform:
#   target status -> the statuses it may be reached from.
# A handler must never move a booking out of any other status. In particular
# a PAID booking is never cancelled by an event, and a CANCELLED booking is
# never marked PAID by an event (that needs a human to decide on a refund).
ALLOWED_STATUS_TRANSITIONS = {
    'PAID': frozenset({'PENDING', 'CONFIRMED'}),
    'CANCELLED': frozenset({'PENDING', 'CONFIRMED'}),
}


def can_transition(current_status, target_status):
    """True if an event handler may move a booking from current to target."""
    return current_status in ALLOWED_STATUS_TRANSITIONS.get(target_status, frozenset())


# Booking status changes that a CONFIRMED REFUND may perform.
#
# Deliberately SEPARATE from ALLOWED_STATUS_TRANSITIONS above, which is left
# exactly as it was. A confirmed refund legitimately cancels a PAID booking,
# but a late or duplicate payment.failed event still must not, so widening the
# map above would have weakened the G11 guarantee. Two maps keep both true:
#   - event handlers   -> can_transition()        (PAID is never cancelled)
#   - confirmed refund -> can_refund_transition() (PAID may be cancelled)
#
# Only a refund.processed webhook, whose signature has been verified and whose
# payment row is already locked, is allowed to use this map.
ALLOWED_REFUND_TRANSITIONS = {
    'CANCELLED': frozenset({'PAID', 'PENDING', 'CONFIRMED'}),
}


def can_refund_transition(current_status, target_status):
    """True if a confirmed refund may move a booking from current to target."""
    return current_status in ALLOWED_REFUND_TRANSITIONS.get(target_status, frozenset())
