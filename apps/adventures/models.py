from django.db import models
from apps.core.models import TimeStampedModel
from apps.locations.models import City


class Adventure(TimeStampedModel):
    DIFFICULTY_CHOICES = [
        ('EASY', 'Easy'),
        ('MEDIUM', 'Medium'),
        ('HARD', 'Hard'),
    ]

    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name='adventures', db_index=True)
    name = models.CharField(max_length=200)
    description = models.TextField()
    price_per_person = models.DecimalField(max_digits=10, decimal_places=2)
    max_capacity = models.IntegerField(default=20)
    current_bookings = models.IntegerField(default=0)
    duration_hours = models.IntegerField(default=2)
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default='EASY')
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    image_url = models.URLField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['price_per_person']

    def __str__(self):
        return f"{self.name} - {self.city.name}"