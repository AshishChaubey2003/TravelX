from rest_framework import serializers
from .models import Booking, BookingItem


class BookingItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingItem
        fields = ['id', 'item_type', 'item_name', 'price_at_booking', 'quantity', 'nights']


class BookingSerializer(serializers.ModelSerializer):
    items = BookingItemSerializer(many=True, read_only=True)

    class Meta:
        model = Booking
        fields = ['id', 'status', 'total_amount', 'check_in', 'check_out', 'items', 'created_at']


class BookingCreateSerializer(serializers.Serializer):
    hotel_id = serializers.UUIDField(required=False)
    adventure_id = serializers.UUIDField(required=False)
    vehicle_id = serializers.UUIDField(required=False)
    check_in = serializers.DateField()
    check_out = serializers.DateField()
    nights = serializers.IntegerField(default=1)
    spots = serializers.IntegerField(default=1)