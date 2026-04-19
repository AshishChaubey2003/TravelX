from django.db import models
from apps.core.models import TimeStampedModel


class City(TimeStampedModel):
    name = models.CharField(max_length=100, db_index=True, unique=True)
    state = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    image_url = models.URLField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Cities"
        ordering = ['name']

    def __str__(self):
        return f"{self.name}, {self.state}"