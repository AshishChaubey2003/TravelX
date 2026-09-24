from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django.db import transaction, models
from .models import Booking
from .serializers import BookingSerializer, BookingCreateSerializer
from .services import BookingService

# Models for restoring availability on cancel
from apps.hotels.models import Hotel
from apps.adventures.models import Adventure


class BookingCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = BookingCreateSerializer(data=request.data)
        if serializer.is_valid():
            try:
                booking = BookingService.create_booking(
                    user=request.user,
                    data=serializer.validated_data
                )
                return Response(
                    BookingSerializer(booking).data,
                    status=status.HTTP_201_CREATED
                )
            except ValueError as e:
                return Response(
                    {'error': str(e)},
                    status=status.HTTP_400_BAD_REQUEST
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class BookingListView(generics.ListAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Booking.objects.filter(
            user=self.request.user
        ).prefetch_related('items')


class BookingDetailView(generics.RetrieveAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Booking.objects.filter(user=self.request.user)


class BookingCancelView(APIView):
    """Cancel a PENDING or CONFIRMED booking and restore availability."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            with transaction.atomic():
                booking = Booking.objects.select_for_update().get(
                    pk=pk, user=request.user
                )

                if booking.status == 'CANCELLED':
                    return Response(
                        {'error': 'Booking is already cancelled.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                if booking.status == 'PAID':
                    return Response(
                        {'error': 'Paid bookings must be refunded, not cancelled.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # restore availability for each item
                for item in booking.items.all():
                    if item.item_type == 'HOTEL':
                        Hotel.objects.filter(id=item.item_id).update(
                            available_rooms=models.F('available_rooms') + item.quantity
                        )
                    elif item.item_type == 'ADVENTURE':
                        Adventure.objects.filter(id=item.item_id).update(
                            current_bookings=models.F('current_bookings') - item.quantity
                        )

                booking.status = 'CANCELLED'
                booking.save(update_fields=['status'])

            return Response(
                BookingSerializer(booking).data,
                status=status.HTTP_200_OK
            )
        except Booking.DoesNotExist:
            return Response(
                {'error': 'Booking not found.'},
                status=status.HTTP_404_NOT_FOUND
            )