from rest_framework import serializers
from .models import Adventure

class AdventureSerializer(serializers.ModelSerializer):
    city_name = serializers.CharField(source='city.name', read_only=True)

    class Meta:
        model = Adventure
        fields = ['id', 'name', 'city_name', 'price_per_person', 'difficulty', 'duration_hours', 'max_capacity', 'current_bookings', 'latitude', 'longitude', 'image_url']