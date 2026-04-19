from django.db import models
from apps.core.models import TimeStampedModel
from apps.locations.models import City


class Hotel(TimeStampedModel):
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name='hotels', db_index=True)
    name = models.CharField(max_length=200)
    description = models.TextField()
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2)
    total_rooms = models.IntegerField(default=10)
    available_rooms = models.IntegerField(default=10)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    amenities = models.JSONField(default=list)
    rating = models.DecimalField(max_digits=2, decimal_places=1, default=4.0)
    image_url = models.URLField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['price_per_night']
        indexes = [
            models.Index(fields=['city', 'is_active']),
            models.Index(fields=['price_per_night']),
        ]

    def __str__(self):
        return f"{self.name} - {self.city.name}"