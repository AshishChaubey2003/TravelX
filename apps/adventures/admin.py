from django.contrib import admin
from .models import Adventure

@admin.register(Adventure)
class AdventureAdmin(admin.ModelAdmin):
    list_display = ['name', 'city', 'price_per_person', 'difficulty']
    list_filter = ['city', 'difficulty']
