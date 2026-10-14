"""
Regression tests for Batch B fixes on `audit/fixes`.

Each test exercises one new guarantee introduced by Batch B. Running these
against the pre-Batch-B baseline (commit d8aaa01) will FAIL in the expected
way; running them against the current working tree must PASS.

- F-017a: BookingCreateSerializer rejects a past `check_in` with 400 and
  does NOT create any Booking or BookingItem rows.
- F-017b: BookingCreateSerializer silently ignores a client-supplied `nights`
  field. The booking is created, nights is computed from the dates, and the
  idempotency fingerprint is stable regardless of the submitted `nights`.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.bookings.models import Booking, BookingItem
from apps.bookings.views import BookingCreateView
from apps.hotels.models import Hotel
from apps.locations.models import City


def _city():
    return City.objects.create(
        name="Reg City", state="S", latitude="12.9", longitude="77.5",
    )


def _user(username="batch_b_user"):
    return User.objects.create_user(
        username=username, email=f"{username}@example.com", password="x",
    )


def _hotel(city):
    return Hotel.objects.create(
        city=city, name="Reg Hotel", description="d",
        price_per_night=Decimal("500.00"),
        total_rooms=10, available_rooms=5,
        latitude="12.9", longitude="77.5", is_active=True,
    )


class PastCheckInIsRejectedTests(TestCase):
    """F-017a — a check_in in the past is a 400 with no DB side effects."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = _user()
        self.city = _city()
        self.hotel = _hotel(self.city)

    def _post(self, **overrides):
        yesterday = timezone.localdate() - timedelta(days=1)
        day_after = yesterday + timedelta(days=2)
        payload = {
            "hotel_id": str(self.hotel.id),
            "check_in": yesterday.isoformat(),
            "check_out": day_after.isoformat(),
        }
        payload.update(overrides)
        request = self.factory.post("/api/v1/bookings/", payload, format="json")
        force_authenticate(request, user=self.user)
        return BookingCreateView.as_view()(request)

    def test_past_check_in_returns_400(self):
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # DRF field-error shape.
        self.assertIn("check_in", response.data)

    def test_past_check_in_creates_no_rows(self):
        before = Booking.objects.count()
        before_items = BookingItem.objects.count()
        response = self._post()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Booking.objects.count(), before)
        self.assertEqual(BookingItem.objects.count(), before_items)

    def test_today_check_in_is_allowed(self):
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)
        response = self._post(
            check_in=today.isoformat(),
            check_out=tomorrow.isoformat(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class NightsFieldIsSilentlyIgnoredTests(TestCase):
    """
    F-017b — the old `nights` field is no longer part of the request shape.
    A client that still sends it must not have its request rejected, and
    the booking must come out with nights computed from the dates.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = _user()
        self.city = _city()
        self.hotel = _hotel(self.city)

    def _post(self, **overrides):
        today = timezone.localdate()
        check_in = today + timedelta(days=10)
        check_out = check_in + timedelta(days=3)
        payload = {
            "hotel_id": str(self.hotel.id),
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
        }
        payload.update(overrides)
        request = self.factory.post("/api/v1/bookings/", payload, format="json")
        force_authenticate(request, user=self.user)
        return BookingCreateView.as_view()(request)

    def test_nights_in_body_is_accepted_and_ignored(self):
        # Legacy client that still ships `nights: 1`.
        response = self._post(nights=1)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        booking = Booking.objects.get(pk=response.data["id"])
        item = booking.items.get(item_type="HOTEL")
        # Nights is computed from the 3-day span; the request's `nights` is irrelevant.
        self.assertEqual(item.nights, 3)

    def test_cosmetically_different_nights_accepted_the_same_way(self):
        response = self._post(nights=99)
        # The old serializer would 400 on nights=99 because the service ignored
        # it but the fingerprint hashed it. We no longer accept the field, so
        # it is silently dropped and the booking is created normally.
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class OTPExpiredMessageMentionsResendTests(TestCase):
    """
    F-020 — when the OTP has expired, the response points the user to the
    Resend OTP flow, not to re-registration (which is blocked because the
    inactive user with that email already exists).
    """

    def test_expired_otp_message_names_resend(self):
        from django.test import Client

        user = User.objects.create_user(
            username="otp_user",
            email="otp_user@example.com",
            password="x",
            is_active=False,
        )
        from apps.accounts.models import EmailVerification

        verification = EmailVerification.objects.create(
            user=user,
            otp="123456",
            is_verified=False,
            expires_at=timezone.now() - timedelta(minutes=1),  # expired
        )

        client = Client()
        response = client.post(
            "/api/v1/auth/verify-otp/",
            data={"email": user.email, "otp": "123456"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        error = response.json().get("error", "")
        self.assertIn("Resend OTP", error)
        # Explicitly assert the old wording is gone, so a regression that
        # restored it would be caught immediately.
        self.assertNotIn("register again", error)
