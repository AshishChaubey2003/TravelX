from django.contrib import admin
from .models import City

@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ['name', 'state', 'is_active']
    search_fields = ['name', 'state']
