from django.db import models
from apps.core.models import TimeStampedModel
from apps.bookings.models import Booking


class Payment(TimeStampedModel):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
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

    def __str__(self):
        return f"Payment {self.booking.id} - {self.status}"
