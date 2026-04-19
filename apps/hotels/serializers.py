from rest_framework import serializers
from .models import Hotel

class HotelListSerializer(serializers.ModelSerializer):
    city_name = serializers.CharField(source='city.name', read_only=True)

    class Meta:
        model = Hotel
        fields = ['id', 'name', 'city_name', 'price_per_night', 'available_rooms', 'rating', 'latitude', 'longitude', 'image_url', 'amenities']

class HotelDetailSerializer(serializers.ModelSerializer):
    city_name = serializers.CharField(source='city.name', read_only=True)

    class Meta:
        model = Hotel
        fields = '__all__'