from django.db import models
from apps.core.models import TimeStampedModel
from apps.bookings.models import Booking


class Payment(TimeStampedModel):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('REFUND_PENDING', 'Refund pending'),
        ('REFUNDED', 'Refunded'),
    ]

    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='payment')
    stripe_payment_intent_id = models.CharField(max_length=200, unique=True, null=True, blank=True)
    stripe_session_id = models.CharField(max_length=200, unique=True, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='inr')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    webhook_received_at = models.DateTimeField(null=True, blank=True)
    raw_webhook = models.JSONField(null=True, blank=True)
    razorpay_refund_id = models.CharField(max_length=200, unique=True, null=True, blank=True)

    def __str__(self):
        return f"Payment {self.booking.id} - {self.status}"


class WebhookEvent(models.Model):
    """
    Inbound Razorpay webhook receipt ledger.

    Mirrors ProcessedEvent's role on the Kafka side (G07): the row is inserted
    in the SAME database transaction as the handler's own changes, so an event
    is never recorded as processed if those changes failed.

    This is NOT a second outbox - nothing is published from here.
    """
    STATUS_PROCESSED = 'PROCESSED'
    STATUS_IGNORED = 'IGNORED'
    STATUS_CHOICES = [
        (STATUS_PROCESSED, 'Processed'),
        (STATUS_IGNORED, 'Ignored'),
    ]

    event_key = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=100)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PROCESSED)
    razorpay_payment_id = models.CharField(max_length=200, blank=True, default='')
    note = models.TextField(blank=True, default='')
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['event_type']),
            models.Index(fields=['received_at']),
        ]

    def __str__(self):
        return f"{self.event_type} {self.event_key} [{self.status}]"
