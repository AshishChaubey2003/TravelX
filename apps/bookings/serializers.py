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
    # F-017: `nights` was previously accepted as a client-supplied field, but
    # BookingService.create_booking computes nights from (check_out - check_in)
    # and ignores whatever the client sent. Leaving it in the input made the
    # idempotency fingerprint (apps/bookings/idempotency.py::booking_fingerprint)
    # vary with a value that had no effect on the actual booking, so two
    # identical booking attempts with cosmetically different `nights` could
    # bypass replay protection. booking_fingerprint reads `.get('nights', 1)`
    # with a default of 1, so removing the field keeps the fingerprint stable.
    spots = serializers.IntegerField(default=1, min_value=1)

    def validate_check_in(self, value):
        # F-017: reject bookings for dates that have already passed. This is a
        # second line of defence on top of the frontend's `min={today}` input;
        # a direct API caller (or a stale FE build) can bypass that control.
        from django.utils import timezone
        today = timezone.localdate()
        if value < today:
            raise serializers.ValidationError(
                'Check-in date cannot be in the past.'
            )
        return value

    def validate(self, data):
        if data['check_out'] <= data['check_in']:
            raise serializers.ValidationError(
                {'check_out': 'check_out must be later than check_in.'}
            )
        return data