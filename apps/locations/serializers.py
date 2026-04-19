from rest_framework import serializers
from .models import City

class CitySerializer(serializers.ModelSerializer):
    hotel_count = serializers.SerializerMethodField()
    adventure_count = serializers.SerializerMethodField()

    class Meta:
        model = City
        fields = ['id', 'name', 'state', 'latitude', 'longitude', 'image_url', 'hotel_count', 'adventure_count']

    def get_hotel_count(self, obj):
        return obj.hotels.filter(is_active=True).count()

    def get_adventure_count(self, obj):
        return obj.adventures.filter(is_active=True).count()