from django.conf import settings
from django.db import transaction
from django.db.models import F, Sum
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

    # F-004 Phase 1: authoritative availability = capacity minus the sum of
    # BookingItem quantities across bookings whose [check_in, check_out)
    # half-open range overlaps the requested range, in a holding status
    # (PENDING/CONFIRMED/PAID; CANCELLED is excluded).
    #
    # Status-writer locking, as actually verified (M15/M16): the Booking.status
    # writers — BookingCancelView, the verify view, handle_payment_failed,
    # handle_payment_success (locked since the M16 race fix; it previously
    # decided on an unlocked read), the refund webhook, and the expiry sweep —
    # each take select_for_update on the booking row before deciding the
    # transition, so a CANCELLED booking leaves this count atomically at
    # commit. That serialisation holds only where the database honours row
    # locks: PostgreSQL. SQLite ignores them, so no SQLite test establishes
    # this guarantee — see the skipped PostgreSQL tests.
    #
    # MUST be called while holding select_for_update on the resource row
    # (create_booking does): on PostgreSQL the row lock serialises competing
    # counts. SQLite ignores row locks, so SQLite tests validate the
    # arithmetic only — NEVER the concurrency.
    @staticmethod
    def _overlap_count(item_type, item_id, check_in, check_out):
        total = BookingItem.objects.filter(
            item_type=item_type,
            item_id=item_id,
            booking__status__in=('PENDING', 'CONFIRMED', 'PAID'),
            booking__check_in__lt=check_out,
            booking__check_out__gt=check_in,
        ).aggregate(n=Sum('quantity'))['n']
        return total or 0

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
            # F-004 Phase 1: the date-aware overlap count is the new,
            # authoritative gate; the legacy global counter below is KEPT as a
            # second, more conservative gate (23 consumers still read it — see
            # docs/audit/PROPOSED_DIFFS_V2.md). Both must pass, so Phase 1 is
            # strictly more restrictive than the counter alone and can never
            # oversell. The counter's date-blind false NEGATIVE (rooms
            # exhausted globally while the requested dates are free) is
            # deliberately unchanged until Phase 2.
            booked = BookingService._overlap_count(
                'HOTEL', hotel.id, check_in, check_out)
            if booked + 1 > hotel.total_rooms:
                raise ValueError("No rooms available for the selected dates.")
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
            # F-004 Phase 1 dual gate (see the hotel branch comment).
            booked = BookingService._overlap_count(
                'ADVENTURE', adventure.id, check_in, check_out)
            if booked + spots > adventure.max_capacity:
                raise ValueError("Not enough spots available for the selected dates.")
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
            # F-004 Phase 1 dual gate (see the hotel branch comment). There is
            # one physical vehicle per Vehicle row, so any overlapping active
            # booking makes it unavailable for the requested range.
            booked = BookingService._overlap_count(
                'VEHICLE', vehicle.id, check_in, check_out)
            if booked >= 1:
                raise ValueError("Vehicle not available for the selected dates.")
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
            raise ValueError(
                "At least one booking item (hotel, adventure, or vehicle) is required."
            )

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
        outbox_event = publish_booking_created(booking)

        # DEMO_INLINE_CONSUMER: after this transaction commits, process the
        # booking.created event inline (sends confirmation email via eager
        # Celery). The on_commit fires only when the outermost atomic block
        # commits, so the booking and outbox row are guaranteed to exist.
        if getattr(settings, 'DEMO_INLINE_CONSUMER', False):
            from apps.kafka_events.consumers import run_inline
            from apps.kafka_events.topics import TOPIC_BOOKING_CREATED
            _evt, _topic = outbox_event, TOPIC_BOOKING_CREATED
            transaction.on_commit(lambda: run_inline(_topic, _evt))

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
