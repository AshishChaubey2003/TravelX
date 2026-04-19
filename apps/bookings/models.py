import uuid
from django.db import models
from django.contrib.auth import get_user_model
from apps.core.models import TimeStampedModel

User = get_user_model()


class Booking(TimeStampedModel):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('CONFIRMED', 'Confirmed'),
        ('PAID', 'Paid'),
        ('CANCELLED', 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookings', db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True)
    stripe_session_id = models.CharField(max_length=200, blank=True, null=True)
    check_in = models.DateField()
    check_out = models.DateField()
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Booking {str(self.id)[:8]} - {self.user.email} - {self.status}"


class BookingItem(models.Model):
    ITEM_TYPE_CHOICES = [
        ('HOTEL', 'Hotel'),
        ('ADVENTURE', 'Adventure'),
        ('VEHICLE', 'Vehicle'),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='items')
    item_type = models.CharField(max_length=20, choices=ITEM_TYPE_CHOICES)
    item_id = models.UUIDField()
    item_name = models.CharField(max_length=200)
    price_at_booking = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=1)
    nights = models.IntegerField(default=1, null=True, blank=True)

    def __str__(self):
        return f"{self.item_type} - {self.item_name}"