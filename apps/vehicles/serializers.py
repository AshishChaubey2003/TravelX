from rest_framework import serializers
from .models import Vehicle

class VehicleSerializer(serializers.ModelSerializer):
    city_name = serializers.CharField(source='city.name', read_only=True)

    class Meta:
        model = Vehicle
        fields = ['id', 'name', 'city_name', 'vehicle_type', 'price_per_day', 'is_available', 'latitude', 'longitude', 'image_url']