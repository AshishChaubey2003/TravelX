"""
Regression tests for BookingService.create_booking (Phase 3 fix):

1. Outbox-enqueue failures during booking creation must propagate instead of
   being swallowed, so the surrounding @transaction.atomic block rolls back
   the booking, its items, and any inventory changes together with the
   outbox write (G08 contract).
2. The happy path still creates exactly one outbox row for a successful
   booking (no regression from the exception-propagation fix).
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from apps.adventures.models import Adventure
from apps.bookings.models import Booking, BookingItem
from apps.bookings.services import BookingService
from apps.hotels.models import Hotel
from apps.kafka_events.models import OutboxEvent
from apps.kafka_events.topics import TOPIC_BOOKING_CREATED
from apps.locations.models import City
from apps.vehicles.models import Vehicle


def _make_city(name="Test City"):
    return City.objects.create(
        name=name, state="Test State", latitude="12.971600", longitude="77.594600",
    )


def _make_user(username="booking_user"):
    return User.objects.create_user(
        username=username, email=f"{username}@example.com", password="x"
    )


def _make_hotel(city, **overrides):
    defaults = dict(
        city=city,
        name="Test Hotel",
        description="A test hotel",
        price_per_night=Decimal("1000.00"),
        total_rooms=10,
        available_rooms=5,
        latitude="12.971600",
        longitude="77.594600",
        is_active=True,
    )
    defaults.update(overrides)
    return Hotel.objects.create(**defaults)


def _make_adventure(city, **overrides):
    defaults = dict(
        city=city,
        name="Test Adventure",
        description="A test adventure",
        price_per_person=Decimal("500.00"),
        max_capacity=20,
        current_bookings=0,
        latitude="12.971600",
        longitude="77.594600",
        is_active=True,
    )
    defaults.update(overrides)
    return Adventure.objects.create(**defaults)


def _make_vehicle(city, **overrides):
    defaults = dict(
        city=city,
        name="Test Vehicle",
        vehicle_type="CAR",
        price_per_day=Decimal("800.00"),
        latitude="12.971600",
        longitude="77.594600",
        is_available=True,
    )
    defaults.update(overrides)
    return Vehicle.objects.create(**defaults)


class CreateBookingOutboxTransactionTests(TestCase):
    """G08: the outbox write and the booking must commit or roll back together."""

    def setUp(self):
        self.city = _make_city()
        self.user = _make_user()
        self.hotel = _make_hotel(self.city, available_rooms=5)

    def test_outbox_enqueue_failure_rolls_back_the_entire_booking(self):
        """
        If writing the outbox row fails, create_booking must raise (not
        swallow the error), and @transaction.atomic must roll back the
        Booking, its BookingItems, and the hotel's inventory decrement
        along with it - no booking may exist without its outbox event.
        """
        with mock.patch(
            "apps.kafka_events.outbox.enqueue_event",
            side_effect=RuntimeError("db write failed"),
        ):
            with self.assertRaises(RuntimeError):
                BookingService.create_booking(
                    user=self.user,
                    data={
                        'hotel_id': str(self.hotel.id),
                        'check_in': '2026-11-01',
                        'check_out': '2026-11-03',
                        'nights': 2,
                    },
                )

        self.assertEqual(Booking.objects.count(), 0)
        self.assertEqual(BookingItem.objects.count(), 0)
        self.assertEqual(OutboxEvent.objects.count(), 0)
        self.hotel.refresh_from_db()
        self.assertEqual(self.hotel.available_rooms, 5)  # inventory decrement rolled back too

    def test_successful_booking_still_enqueues_exactly_one_outbox_event(self):
        """Happy path is unaffected by the exception-propagation fix."""
        booking = BookingService.create_booking(
            user=self.user,
            data={
                'hotel_id': str(self.hotel.id),
                'check_in': '2026-11-01',
                'check_out': '2026-11-03',
                'nights': 2,
            },
        )

        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(OutboxEvent.objects.count(), 1)
        row = OutboxEvent.objects.get()
        self.assertEqual(row.topic, TOPIC_BOOKING_CREATED)
        self.hotel.refresh_from_db()
        self.assertEqual(self.hotel.available_rooms, 4)


class CreateBookingDateAndQuantityValidationTests(TestCase):
    def setUp(self):
        self.city = _make_city()
        self.user = _make_user(username="date_validation_user")
        self.hotel = _make_hotel(self.city, available_rooms=5)
        self.adventure = _make_adventure(self.city, max_capacity=10, current_bookings=0)

    def test_check_out_not_after_check_in_is_rejected(self):
        with self.assertRaises(ValueError):
            BookingService.create_booking(
                user=self.user,
                data={
                    'hotel_id': str(self.hotel.id),
                    'check_in': '2026-11-03',
                    'check_out': '2026-11-01',
                    'nights': 2,
                },
            )
        self.assertEqual(Booking.objects.count(), 0)

    def test_client_supplied_nights_is_ignored_in_favor_of_derived_duration(self):
        booking = BookingService.create_booking(
            user=self.user,
            data={
                'hotel_id': str(self.hotel.id),
                'check_in': '2026-11-01',
                'check_out': '2026-11-03',
                'nights': 100,
            },
        )
        item = booking.items.get(item_type='HOTEL')
        self.assertEqual(item.nights, 2)
        self.assertEqual(item.price_at_booking, self.hotel.price_per_night * 2)

    def test_adventure_nonpositive_spots_is_rejected(self):
        with self.assertRaises(ValueError):
            BookingService.create_booking(
                user=self.user,
                data={
                    'adventure_id': str(self.adventure.id),
                    'check_in': '2026-11-01',
                    'check_out': '2026-11-03',
                    'spots': 0,
                },
            )
        self.assertEqual(Booking.objects.count(), 0)
