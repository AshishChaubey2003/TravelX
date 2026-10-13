from django.db import models
from django.utils import timezone


class ProcessedEvent(models.Model):
    """
    Ledger of Kafka events the consumer has already handled (checklist G07).

    event_key is unique. The consumer inserts the row in the same database
    transaction as the handler's own database changes, so either both are
    committed or neither is.
    """
    event_key = models.CharField(max_length=255, unique=True)
    topic = models.CharField(max_length=100)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['processed_at']),
        ]

    def __str__(self):
        return f"{self.topic} {self.event_key}"


class OutboxEvent(models.Model):
    """
    Transactional outbox (checklist G08).

    Rows are written in the SAME database transaction as the change they
    describe (e.g. a new booking). A relay (manage.py publish_outbox) then
    delivers them to Kafka and records the outcome, so a Kafka outage can no
    longer silently lose an event.

    PENDING   waiting to be (re)published
    PUBLISHED delivery to Kafka was confirmed
    DEAD      gave up after max_attempts; needs a human to look and replay
              (manage.py recovery replay-outbox)
    """
    STATUS_PENDING = 'PENDING'
    STATUS_PUBLISHED = 'PUBLISHED'
    STATUS_DEAD = 'DEAD'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_DEAD, 'Dead'),
    ]

    event_id = models.UUIDField(unique=True)
    topic = models.CharField(max_length=100)
    key = models.CharField(max_length=255)
    payload = models.JSONField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', 'next_attempt_at']),
        ]

    def __str__(self):
        return f"{self.topic} {self.event_id} [{self.status}]"


class FailedEvent(models.Model):
    """
    Consumer-side dead-letter record (checklist G10).

    RETRYING  the handler failed; the consumer rewinds and retries
    DEAD      failed max_attempts times; the offset was committed so the
              partition is not blocked; waiting for a human to fix the cause
              and replay (manage.py recovery replay-events)
    RESOLVED  a later retry succeeded
    REPLAYED  replayed successfully by an operator
    """
    STATUS_RETRYING = 'RETRYING'
    STATUS_DEAD = 'DEAD'
    STATUS_RESOLVED = 'RESOLVED'
    STATUS_REPLAYED = 'REPLAYED'
    STATUS_CHOICES = [
        (STATUS_RETRYING, 'Retrying'),
        (STATUS_DEAD, 'Dead'),
        (STATUS_RESOLVED, 'Resolved'),
        (STATUS_REPLAYED, 'Replayed'),
    ]

    event_key = models.CharField(max_length=255, unique=True)
    topic = models.CharField(max_length=100)
    partition = models.IntegerField(null=True, blank=True)
    offset = models.BigIntegerField(null=True, blank=True)
    payload = models.JSONField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_RETRYING)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    dead_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.topic} {self.event_key} [{self.status}]"


class FailedTask(models.Model):
    """
    Record of a Celery task that failed permanently (checklist G10), written
    by the task base class's on_failure. Replayable with
    manage.py recovery replay-tasks.
    """
    STATUS_FAILED = 'FAILED'
    STATUS_REPLAYED = 'REPLAYED'
    STATUS_CHOICES = [
        (STATUS_FAILED, 'Failed'),
        (STATUS_REPLAYED, 'Replayed'),
    ]

    task_name = models.CharField(max_length=255)
    task_id = models.CharField(max_length=255, unique=True)
    args = models.JSONField(default=list)
    kwargs = models.JSONField(default=dict)
    error = models.TextField(blank=True, default='')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_FAILED)
    replay_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    replayed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.task_name} {self.task_id} [{self.status}]"