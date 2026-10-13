"""
Batch 1 regression tests: inventory restoration on cancellation (pass today),
and payment-failure inventory behaviour (KNOWN BUG R2 - currently fails).

PaymentFailedInventoryKnownBugR2Tests encodes the post-fix behaviour and
therefore FAILS against the current code. It is a normal regression test that
will pass once R2 is fixed - NOT a unittest.expectedFailure.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.adventures.models import Adventure
from apps.bookings.models import Booking, BookingItem
from apps.bookings.views import BookingCancelView
from apps.hotels.models import Hotel
from apps.locations.models import City
from apps.kafka_events.consumers import handle_payment_failed


def _city():
    return City.objects.create(name="Inv City", state="S", latitude="12.9", longitude="77.5")


def _user():
    return User.objects.create_user(username="inv_user", email="inv@example.com", password="x")


def _booking(user, status="PENDING"):
    return Booking.objects.create(
        user=user, status=status, total_amount=Decimal("1000.00"),
        check_in=date(2030, 1, 1), check_out=date(2030, 1, 3),
    )


class CancelRestoresInventoryTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = _user()
        self.city = _city()

    def _cancel(self, booking):
        request = self.factory.post(f"/api/v1/bookings/{booking.id}/cancel/")
        force_authenticate(request, user=self.user)
        return BookingCancelView.as_view()(request, pk=booking.id)

    def test_cancel_restores_hotel_rooms(self):
        hotel = Hotel.objects.create(
            city=self.city, name="H", description="d", price_per_night=Decimal("1000.00"),
            total_rooms=10, available_rooms=4, latitude="12.9", longitude="77.5", is_active=True,
        )
        booking = _booking(self.user)
        BookingItem.objects.create(
            booking=booking, item_type="HOTEL", item_id=hotel.id,
            item_name=hotel.name, price_at_booking=Decimal("1000.00"), quantity=1, nights=2,
        )
        resp = self._cancel(booking)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        hotel.refresh_from_db()
        self.assertEqual(hotel.available_rooms, 5)

    def test_cancel_restores_adventure_capacity(self):
        adventure = Adventure.objects.create(
            city=self.city, name="A", description="d", price_per_person=Decimal("500.00"),
            max_capacity=20, current_bookings=3, latitude="12.9", longitude="77.5", is_active=True,
        )
        booking = _booking(self.user)
        BookingItem.objects.create(
            booking=booking, item_type="ADVENTURE", item_id=adventure.id,
            item_name=adventure.name, price_at_booking=Decimal("1500.00"), quantity=3, nights=None,
        )
        resp = self._cancel(booking)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        adventure.refresh_from_db()
        self.assertEqual(adventure.current_bookings, 0)


class PaymentFailedCancelsPendingBookingTests(TestCase):
    """Current, correct behaviour: a payment.failed event cancels a PENDING booking."""

    def setUp(self):
        self.user = _user()

    def test_payment_failed_cancels_pending_booking(self):
        booking = _booking(self.user, status="PENDING")
        handle_payment_failed({"booking_id": str(booking.id)})
        booking.refresh_from_db()
        self.assertEqual(booking.status, "CANCELLED")


class PaymentFailedInventoryKnownBugR2Tests(TestCase):
    """
    KNOWN BUG R2 - EXPECTED TO FAIL until the Batch 3 fix lands.

    handle_payment_failed() cancels the booking but does NOT restore the
    inventory it was holding, so a failed/abandoned payment permanently leaks
    a room. This asserts the post-fix behaviour and fails against current code.
    """

    def setUp(self):
        self.user = _user()
        self.city = _city()

    def test_payment_failed_restores_hotel_inventory(self):
        hotel = Hotel.objects.create(
            city=self.city, name="H", description="d", price_per_night=Decimal("1000.00"),
            total_rooms=10, available_rooms=4, latitude="12.9", longitude="77.5", is_active=True,
        )
        booking = _booking(self.user, status="PENDING")
        BookingItem.objects.create(
            booking=booking, item_type="HOTEL", item_id=hotel.id,
            item_name=hotel.name, price_at_booking=Decimal("1000.00"), quantity=1, nights=2,
        )
        handle_payment_failed({"booking_id": str(booking.id)})
        booking.refresh_from_db()
        self.assertEqual(booking.status, "CANCELLED")
        hotel.refresh_from_db()
        self.assertEqual(hotel.available_rooms, 5)  # KNOWN BUG R2: currently stays 4