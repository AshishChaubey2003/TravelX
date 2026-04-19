from django.contrib import admin
from .models import Hotel

@admin.register(Hotel)
class HotelAdmin(admin.ModelAdmin):
    list_display = ['name', 'city', 'price_per_night', 'available_rooms', 'rating']
    search_fields = ['name']
    list_filter = ['city', 'is_active']