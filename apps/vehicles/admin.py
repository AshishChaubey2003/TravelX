from django.contrib import admin
from .models import Vehicle

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ['name', 'city', 'vehicle_type', 'price_per_day', 'is_available']
    list_filter = ['city', 'vehicle_type']