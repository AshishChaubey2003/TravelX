"""
Batch 1 regression tests: booking Idempotency-Key replay and conflicts.
All tests assert CURRENT, correct behaviour and must pass as-is.
"""
import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.bookings.models import Booking
from apps.bookings.views import BookingCreateView
from apps.hotels.models import Hotel
from apps.locations.models import City


def _city():
    return City.objects.create(name="Idem City", state="S", latitude="12.9", longitude="77.5")


def _user(username):
    return User.objects.create_user(username=username, email=f"{username}@example.com", password="x")


def _hotel(city, rooms=5):
    return Hotel.objects.create(
        city=city, name="H", description="d", price_per_night=Decimal("1000.00"),
        total_rooms=10, available_rooms=rooms, latitude="12.9", longitude="77.5", is_active=True,
    )


class BookingIdempotencyTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = _user("idem_user")
        self.city = _city()
        self.hotel = _hotel(self.city)

    def _post(self, body, key=None, user=None):
        extra = {}
        if key is not None:
            extra["HTTP_IDEMPOTENCY_KEY"] = key
        request = self.factory.post("/api/v1/bookings/", body, format="json", **extra)
        force_authenticate(request, user=user or self.user)
        return BookingCreateView.as_view()(request)

    def _body(self, check_out="2030-01-03"):
        return {"hotel_id": str(self.hotel.id), "check_in": "2030-01-01", "check_out": check_out, "nights": 2}

    def test_first_request_with_key_creates_one_booking(self):
        resp = self._post(self._body(), key=str(uuid.uuid4()))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Booking.objects.count(), 1)

    def test_same_key_same_payload_replays_without_second_booking(self):
        key = str(uuid.uuid4())
        first = self._post(self._body(), key=key)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self._post(self._body(), key=key)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second["Idempotent-Replay"], "true")
        self.assertEqual(Booking.objects.count(), 1)
        self.hotel.refresh_from_db()
        self.assertEqual(self.hotel.available_rooms, 4)  # decremented exactly once

    def test_same_key_different_payload_is_conflict(self):
        key = str(uuid.uuid4())
        self._post(self._body(check_out="2030-01-03"), key=key)
        resp = self._post(self._body(check_out="2030-01-09"), key=key)
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(Booking.objects.count(), 1)

    def test_same_key_different_user_is_conflict(self):
        key = str(uuid.uuid4())
        self._post(self._body(), key=key)
        other = _user("idem_other")
        resp = self._post(self._body(), key=key, user=other)
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(Booking.objects.count(), 1)

    def test_invalid_key_is_rejected(self):
        resp = self._post(self._body(), key="not-a-uuid")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Booking.objects.count(), 0)

    def test_no_key_still_creates_booking(self):
        resp = self._post(self._body())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Booking.objects.count(), 1)