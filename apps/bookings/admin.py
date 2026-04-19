from django.contrib import admin
from .models import Booking, BookingItem

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'status', 'total_amount', 'created_at']
    list_filter = ['status']

@admin.register(BookingItem)
class BookingItemAdmin(admin.ModelAdmin):
    list_display = ['booking', 'item_type', 'item_name', 'price_at_booking']