from rest_framework import serializers
from .models import City

class CitySerializer(serializers.ModelSerializer):
    hotel_count = serializers.SerializerMethodField()
    adventure_count = serializers.SerializerMethodField()

    class Meta:
        model = City
        fields = ['id', 'name', 'state', 'latitude', 'longitude', 'image_url', 'hotel_count', 'adventure_count']

    # Both counts prefer the annotation added by CityListView.get_queryset()
    # (one query for the whole page instead of one per city per field). The
    # per-object fallback keeps the serializer correct on its own, e.g. when
    # it is used with a plain City instance or an un-annotated queryset.
    def get_hotel_count(self, obj):
        annotated = getattr(obj, 'annotated_hotel_count', None)
        if annotated is not None:
            return annotated
        return obj.hotels.filter(is_active=True).count()

    def get_adventure_count(self, obj):
        annotated = getattr(obj, 'annotated_adventure_count', None)
        if annotated is not None:
            return annotated
        return obj.adventures.filter(is_active=True).count()