"""
Recovery operations for failed async work (checklists G10 + G11).

Every function here is what the `manage.py recovery ...` command calls.
Replay only after you have fixed the underlying cause; replaying into the
same failure just fails again (safely: nothing is lost or duplicated).
"""
import logging

from celery import current_app
from django.db.models import Count, Min
from django.utils import timezone

from .models import FailedEvent, FailedTask, OutboxEvent
from .policy import REPLAYABLE_TASK_NAMES

logger = logging.getLogger(__name__)


def _select(queryset, ids):
    if ids is not None:
        queryset = queryset.filter(pk__in=ids)
    return queryset


def _counts(model):
    rows = model.objects.values('status').annotate(n=Count('id'))
    return {row['status']: row['n'] for row in rows}


def status_summary():
    """Counts of everything that needs attention, by status."""
    oldest = OutboxEvent.objects.filter(
        status=OutboxEvent.STATUS_PENDING
    ).aggregate(oldest=Min('created_at'))['oldest']
    oldest_age = None if oldest is None else (timezone.now() - oldest).total_seconds()
    return {
        'outbox': _counts(OutboxEvent),
        'failed_events': _counts(FailedEvent),
        'failed_tasks': _counts(FailedTask),
        'oldest_pending_outbox_age_seconds': oldest_age,
    }


def replay_dead_outbox(ids=None):
    """Put DEAD outbox events back to PENDING; the relay then publishes them.
    Returns the number of events re-queued."""
    queryset = _select(OutboxEvent.objects.filter(status=OutboxEvent.STATUS_DEAD), ids)
    return queryset.update(
        status=OutboxEvent.STATUS_PENDING,
        attempts=0,
        last_error='',
        next_attempt_at=timezone.now(),
    )


def replay_dead_events(ids=None):
    """
    Re-run DEAD consumer events through the same exactly-once-effect path the
    consumer uses. Returns {'replayed': n, 'failed': n}.
    """
    from .consumers import process_event_once

    result = {'replayed': 0, 'failed': 0}
    queryset = _select(FailedEvent.objects.filter(status=FailedEvent.STATUS_DEAD), ids)
    for event in queryset.order_by('id'):
        try:
            process_event_once(event.topic, event.payload, event.event_key)
        except Exception as exc:
            event.last_error = str(exc)[:2000]
            event.save(update_fields=['last_error', 'updated_at'])
            result['failed'] += 1
            logger.error('Replay of failed event %s failed: %s', event.event_key, exc)
            continue
        event.status = FailedEvent.STATUS_REPLAYED
        event.save(update_fields=['status', 'updated_at'])
        result['replayed'] += 1
    return result


def replay_failed_tasks(ids=None):
    """
    Re-queue FAILED Celery tasks with their original arguments. Returns
    {'replayed': n, 'failed': n}. Needs the Celery broker to be reachable.

    G11: only task names listed in policy.REPLAYABLE_TASK_NAMES are re-queued.
    A FailedTask row naming anything else is refused, so a tampered row cannot
    be used to run an arbitrary task.
    """
    result = {'replayed': 0, 'failed': 0}
    queryset = _select(FailedTask.objects.filter(status=FailedTask.STATUS_FAILED), ids)
    for task in queryset.order_by('id'):
        if task.task_name not in REPLAYABLE_TASK_NAMES:
            task.replay_error = f'refused: task {task.task_name!r} is not allowlisted for replay'
            task.save(update_fields=['replay_error'])
            result['failed'] += 1
            logger.error('Replay refused for task %s: %r is not allowlisted',
                         task.task_id, task.task_name)
            continue
        try:
            current_app.send_task(task.task_name, args=task.args, kwargs=task.kwargs)
        except Exception as exc:
            task.replay_error = str(exc)[:2000]
            task.save(update_fields=['replay_error'])
            result['failed'] += 1
            logger.error('Replay of failed task %s failed: %s', task.task_id, exc)
            continue
        task.status = FailedTask.STATUS_REPLAYED
        task.replay_error = ''
        task.replayed_at = timezone.now()
        task.save(update_fields=['status', 'replay_error', 'replayed_at'])
        result['replayed'] += 1
    return result