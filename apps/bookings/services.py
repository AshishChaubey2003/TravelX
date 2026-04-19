from django.db import transaction
from .models import Booking, BookingItem
from apps.hotels.models import Hotel
from apps.adventures.models import Adventure
from apps.vehicles.models import Vehicle
import uuid


class BookingService:

    @staticmethod
    @transaction.atomic
    def create_booking(user, data):
        hotel_id = data.get('hotel_id')
        adventure_id = data.get('adventure_id')
        vehicle_id = data.get('vehicle_id')
        check_in = data.get('check_in')
        check_out = data.get('check_out')
        nights = data.get('nights', 1)

        total_amount = 0
        items = []

        # Hotel booking
        if hotel_id:
            hotel = Hotel.objects.select_for_update().get(
                id=hotel_id, is_active=True
            )
            if hotel.available_rooms < 1:
                raise ValueError("No rooms available!")

            price = hotel.price_per_night * nights
            total_amount += price
            hotel.available_rooms -= 1
            hotel.save()

            items.append({
                'item_type': 'HOTEL',
                'item_id': hotel.id,
                'item_name': hotel.name,
                'price_at_booking': price,
                'quantity': 1,
                'nights': nights,
            })

        # Adventure booking
        if adventure_id:
            adventure = Adventure.objects.select_for_update().get(
                id=adventure_id, is_active=True
            )
            spots = data.get('spots', 1)
            if adventure.current_bookings + spots > adventure.max_capacity:
                raise ValueError("Not enough spots available!")

            price = adventure.price_per_person * spots
            total_amount += price
            adventure.current_bookings += spots
            adventure.save()

            items.append({
                'item_type': 'ADVENTURE',
                'item_id': adventure.id,
                'item_name': adventure.name,
                'price_at_booking': price,
                'quantity': spots,
                'nights': None,
            })

        # Vehicle booking
        if vehicle_id:
            vehicle = Vehicle.objects.select_for_update().get(
                id=vehicle_id
            )
            if not vehicle.is_available:
                raise ValueError("Vehicle not available!")

            price = vehicle.price_per_day * nights
            total_amount += price
            vehicle.is_available = False
            vehicle.save()

            items.append({
                'item_type': 'VEHICLE',
                'item_id': vehicle.id,
                'item_name': vehicle.name,
                'price_at_booking': price,
                'quantity': 1,
                'nights': nights,
            })

        if not items:
            raise ValueError("Kuch toh book karo bhai!")

        # Create Booking
        booking = Booking.objects.create(
            user=user,
            total_amount=total_amount,
            check_in=check_in,
            check_out=check_out,
            status='PENDING',
        )

        # Create BookingItems
        for item in items:
            BookingItem.objects.create(
                booking=booking,
                **item
            )

        return booking