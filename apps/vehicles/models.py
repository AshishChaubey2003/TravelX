from django.db import models
from apps.core.models import TimeStampedModel
from apps.locations.models import City


class Vehicle(TimeStampedModel):
    TYPE_CHOICES = [
        ('BIKE', 'Bike'),
        ('CAR', 'Car'),
        ('SCOOTER', 'Scooter'),
    ]

    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name='vehicles', db_index=True)
    name = models.CharField(max_length=200)
    vehicle_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    price_per_day = models.DecimalField(max_digits=10, decimal_places=2)
    is_available = models.BooleanField(default=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    image_url = models.URLField(blank=True, null=True)

    class Meta:
        ordering = ['price_per_day']

    def __str__(self):
        return f"{self.name} - {self.city.name}"