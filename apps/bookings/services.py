from django.db import transaction
from django.db.models import F
from django.utils.dateparse import parse_date
from .models import Booking, BookingItem
from apps.hotels.models import Hotel
from apps.adventures.models import Adventure
from apps.vehicles.models import Vehicle
from apps.kafka_events.producers import publish_booking_created
import logging
import uuid

logger = logging.getLogger(__name__)


class BookingService:

    @staticmethod
    @transaction.atomic
    def create_booking(user, data, idempotency_key=None, idempotency_fingerprint=None):
        hotel_id = data.get('hotel_id')
        adventure_id = data.get('adventure_id')
        vehicle_id = data.get('vehicle_id')
        check_in = data.get('check_in')
        check_out = data.get('check_out')
        if isinstance(check_in, str):
            check_in = parse_date(check_in)
        if isinstance(check_out, str):
            check_out = parse_date(check_out)
        if not check_in or not check_out or check_out <= check_in:
            raise ValueError("check_out must be later than check_in.")
        nights = (check_out - check_in).days

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
            if spots <= 0:
                raise ValueError("spots must be a positive integer.")
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
        booking_fields = {
            'user': user,
            'total_amount': total_amount,
            'check_in': check_in,
            'check_out': check_out,
            'status': 'PENDING',
        }
        # Stage 2: only set these when the caller supplied them. Passing
        # idempotency_key=None explicitly would try to INSERT NULL into a
        # NOT NULL column and bypass the model's uuid4 default; omitting the
        # keys instead keeps behaviour byte-identical for existing callers.
        # The UNIQUE constraint on idempotency_key fires as part of THIS
        # transaction, so a duplicate key rolls back the inventory decrements
        # above along with the booking.
        if idempotency_key is not None:
            booking_fields['idempotency_key'] = idempotency_key
        if idempotency_fingerprint is not None:
            booking_fields['idempotency_fingerprint'] = idempotency_fingerprint

        booking = Booking.objects.create(**booking_fields)

        # Create BookingItems
        for item in items:
            BookingItem.objects.create(
                booking=booking,
                **item
            )

        # G08: publish_booking_created only writes to the transactional
        # outbox (it never talks to Kafka directly), so it must succeed
        # inside this same @transaction.atomic block as the booking itself.
        # If it raises, the whole transaction - booking, inventory updates,
        # and the outbox row - rolls back together, instead of silently
        # committing a booking with no outbox event.
        publish_booking_created(booking)

        return booking

    @staticmethod
    def release_inventory(booking):
        """
        Give back what create_booking reserved for this booking.

        The caller MUST hold the booking's row lock and call this only on the
        transition INTO CANCELLED, in the same transaction as the status change.
        That gating is what makes the release happen exactly once: a vehicle is
        only a boolean, so a second release could free one that another booking
        has since taken.
        """
        for item in booking.items.all():
            if item.item_type == 'HOTEL':
                Hotel.objects.filter(id=item.item_id).update(
                    available_rooms=F('available_rooms') + item.quantity
                )
            elif item.item_type == 'ADVENTURE':
                Adventure.objects.filter(id=item.item_id).update(
                    current_bookings=F('current_bookings') - item.quantity
                )
            elif item.item_type == 'VEHICLE':
                Vehicle.objects.filter(id=item.item_id).update(is_available=True)
