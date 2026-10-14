"""
Regression tests for BookingCreateView (Phase 3 fix):

A hotel_id / adventure_id / vehicle_id that does not exist must return a
clean 404 with a JSON error body - never an unhandled 500 with a Django
DEBUG traceback. Valid requests, and business-rule (ValueError) rejections,
must keep working exactly as before.
"""
from decimal import Decimal
import uuid

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.adventures.models import Adventure
from apps.bookings.models import Booking
from apps.bookings.views import BookingCreateView, BookingCancelView
from apps.hotels.models import Hotel
from apps.locations.models import City
from apps.vehicles.models import Vehicle


def _make_city(name="Test City"):
    return City.objects.create(
        name=name, state="Test State", latitude="12.971600", longitude="77.594600",
    )


def _make_user(username="view_user"):
    return User.objects.create_user(
        username=username, email=f"{username}@example.com", password="x"
    )


def _make_hotel(city, **overrides):
    defaults = dict(
        city=city, name="Test Hotel", description="A test hotel",
        price_per_night=Decimal("1000.00"), total_rooms=10, available_rooms=5,
        latitude="12.971600", longitude="77.594600", is_active=True,
    )
    defaults.update(overrides)
    return Hotel.objects.create(**defaults)


def _make_adventure(city, **overrides):
    defaults = dict(
        city=city, name="Test Adventure", description="A test adventure",
        price_per_person=Decimal("500.00"), max_capacity=20, current_bookings=0,
        latitude="12.971600", longitude="77.594600", is_active=True,
    )
    defaults.update(overrides)
    return Adventure.objects.create(**defaults)


def _make_vehicle(city, **overrides):
    defaults = dict(
        city=city, name="Test Vehicle", vehicle_type="CAR",
        price_per_day=Decimal("800.00"), latitude="12.971600", longitude="77.594600",
        is_available=True,
    )
    defaults.update(overrides)
    return Vehicle.objects.create(**defaults)


class BookingCreateInvalidResourceIdTests(TestCase):
    """BookingCreateView must turn a bad hotel/adventure/vehicle id into a 404, not a 500."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = _make_user()
        self.city = _make_city()

    def _post(self, payload):
        request = self.factory.post('/api/bookings/', payload, format='json')
        force_authenticate(request, user=self.user)
        return BookingCreateView.as_view()(request)

    def test_nonexistent_hotel_id_returns_404_not_500(self):
        response = self._post({
            'hotel_id': str(uuid.uuid4()),
            'check_in': '2026-11-01',
            'check_out': '2026-11-03',
            'nights': 2,
        })
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('error', response.data)
        self.assertEqual(Booking.objects.count(), 0)

    def test_nonexistent_adventure_id_returns_404_not_500(self):
        response = self._post({
            'adventure_id': str(uuid.uuid4()),
            'check_in': '2026-11-01',
            'check_out': '2026-11-03',
            'spots': 1,
        })
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('error', response.data)
        self.assertEqual(Booking.objects.count(), 0)

    def test_nonexistent_vehicle_id_returns_404_not_500(self):
        response = self._post({
            'vehicle_id': str(uuid.uuid4()),
            'check_in': '2026-11-01',
            'check_out': '2026-11-03',
            'nights': 2,
        })
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('error', response.data)
        self.assertEqual(Booking.objects.count(), 0)

    def test_valid_hotel_id_still_returns_201(self):
        """Existing valid-request behaviour must be unaffected by the fix."""
        hotel = _make_hotel(self.city)
        response = self._post({
            'hotel_id': str(hotel.id),
            'check_in': '2026-11-01',
            'check_out': '2026-11-03',
            'nights': 2,
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Booking.objects.count(), 1)

    def test_valid_adventure_id_still_returns_201(self):
        adventure = _make_adventure(self.city)
        response = self._post({
            'adventure_id': str(adventure.id),
            'check_in': '2026-11-01',
            'check_out': '2026-11-03',
            'spots': 1,
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Booking.objects.count(), 1)

    def test_valid_vehicle_id_still_returns_201(self):
        vehicle = _make_vehicle(self.city)
        response = self._post({
            'vehicle_id': str(vehicle.id),
            'check_in': '2026-11-01',
            'check_out': '2026-11-03',
            'nights': 2,
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Booking.objects.count(), 1)

    def test_business_rule_violation_still_returns_400_not_404(self):
        """A ValueError (e.g. no rooms available) must stay a 400, not become a 404."""
        hotel = _make_hotel(self.city, available_rooms=0)
        response = self._post({
            'hotel_id': str(hotel.id),
            'check_in': '2026-11-01',
            'check_out': '2026-11-03',
            'nights': 2,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)
        self.assertEqual(Booking.objects.count(), 0)


class BookingCancelVehicleAvailabilityTests(TestCase):
    """F-19: cancelling a vehicle booking must restore Vehicle.is_available."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = _make_user(username="cancel_user")
        self.city = _make_city()

    def _create_booking(self, vehicle):
        request = self.factory.post('/api/bookings/', {
            'vehicle_id': str(vehicle.id),
            'check_in': '2026-11-01',
            'check_out': '2026-11-03',
            'nights': 2,
        }, format='json')
        force_authenticate(request, user=self.user)
        return BookingCreateView.as_view()(request)

    def _cancel(self, booking_id):
        request = self.factory.post(f'/api/bookings/{booking_id}/cancel/')
        force_authenticate(request, user=self.user)
        return BookingCancelView.as_view()(request, pk=booking_id)

    def test_cancel_restores_vehicle_availability(self):
        vehicle = _make_vehicle(self.city)
        create_response = self._create_booking(vehicle)
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        vehicle.refresh_from_db()
        self.assertFalse(vehicle.is_available)

        booking = Booking.objects.get(user=self.user)
        cancel_response = self._cancel(booking.id)
        self.assertEqual(cancel_response.status_code, status.HTTP_200_OK)

        vehicle.refresh_from_db()
        self.assertTrue(vehicle.is_available)

    def test_repeated_cancellation_does_not_error_or_change_state(self):
        vehicle = _make_vehicle(self.city)
        self._create_booking(vehicle)
        booking = Booking.objects.get(user=self.user)

        first = self._cancel(booking.id)
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        vehicle.refresh_from_db()
        self.assertTrue(vehicle.is_available)

        second = self._cancel(booking.id)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', second.data)
        vehicle.refresh_from_db()
        self.assertTrue(vehicle.is_available)
