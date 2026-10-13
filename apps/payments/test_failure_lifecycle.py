"""
Batch 3 / Stage C regression tests: payment failure must release inventory exactly once (fixes R2),
duplicate failure events, late capture / late verify after cancellation, and the cancel path.

Gateway and Celery are never contacted: webhooks are signed locally, receipt scheduling is
patched. These run on SQLite, where select_for_update() is a no-op, so they prove the
once-only logic (status-transition gating + event ledgers) but NOT true row-lock
concurrency, which needs PostgreSQL.
"""
import hashlib
import hmac
import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.adventures.models import Adventure
from apps.bookings.models import Booking
from apps.bookings.services import BookingService
from apps.hotels.models import Hotel
from apps.kafka_events.consumers import handle_payment_failed, process_event_once
from apps.kafka_events.models import OutboxEvent
from apps.kafka_events.topics import TOPIC_PAYMENT_FAILED, TOPIC_PAYMENT_SUCCESS
from apps.locations.models import City
from apps.payments.models import Payment
from apps.vehicles.models import Vehicle

SECRET = "whsec_batch3_test_secret"
WEBHOOK_URL = "/api/v1/payments/razorpay/webhook/"
VERIFY_URL = "/api/v1/payments/razorpay/verify/"


def _sign(body):
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


class FailureLifecycleBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="fl_user", email="fl@example.com", password="x")
        self.user2 = User.objects.create_user(username="fl_user2", email="fl2@example.com", password="x")
        city = City.objects.create(name="FL City", state="S", latitude="12.9", longitude="77.5")
        self.hotel = Hotel.objects.create(
            city=city, name="H", description="d", price_per_night=Decimal("1000.00"),
            total_rooms=10, available_rooms=5, latitude="12.9", longitude="77.5", is_active=True)
        self.adventure = Adventure.objects.create(
            city=city, name="A", description="d", price_per_person=Decimal("500.00"),
            max_capacity=20, current_bookings=3, latitude="12.9", longitude="77.5", is_active=True)
        self.vehicle = Vehicle.objects.create(
            city=city, name="V", vehicle_type="CAR", price_per_day=Decimal("800.00"),
            is_available=True, latitude="12.9", longitude="77.5")

    # -- helpers -------------------------------------------------------
    def book(self, user=None, hotel=False, adventure=False, vehicle=False):
        data = {"check_in": date(2030, 1, 1), "check_out": date(2030, 1, 3)}
        if hotel:
            data["hotel_id"] = self.hotel.id
        if adventure:
            data["adventure_id"] = self.adventure.id
            data["spots"] = 2
        if vehicle:
            data["vehicle_id"] = self.vehicle.id
        return BookingService.create_booking(user or self.user, data)

    def pay(self, booking, order_id="order_F1", status="PENDING", intent=None):
        return Payment.objects.create(
            booking=booking, amount=booking.total_amount, currency="inr",
            status=status, stripe_session_id=order_id, stripe_payment_intent_id=intent)

    def rooms(self):
        return Hotel.objects.get(pk=self.hotel.pk).available_rooms

    def taken_spots(self):
        return Adventure.objects.get(pk=self.adventure.pk).current_bookings

    def vehicle_free(self):
        return Vehicle.objects.get(pk=self.vehicle.pk).is_available

    def status_of(self, booking):
        return Booking.objects.get(pk=booking.pk).status

    def failed_event(self, booking):
        return {"booking_id": str(booking.id)}

    def consume(self, outbox_event):
        key = f"{outbox_event.topic}:event:{outbox_event.payload['event_id']}"
        return process_event_once(outbox_event.topic, outbox_event.payload, key)

    def webhook(self, event, kind, entity):
        body = json.dumps({"event": event, "payload": {kind: {"entity": entity}}},
                          sort_keys=True).encode()
        return self.client.post(WEBHOOK_URL, data=body, content_type="application/json",
                                HTTP_X_RAZORPAY_SIGNATURE=_sign(body))


class FailureReleasesInventoryTests(FailureLifecycleBase):
    def test_hotel_room_is_released_once_even_if_the_event_repeats(self):
        booking = self.book(hotel=True)
        self.assertEqual(self.rooms(), 4)
        handle_payment_failed(self.failed_event(booking))
        self.assertEqual(self.rooms(), 5)
        self.assertEqual(self.status_of(booking), "CANCELLED")
        handle_payment_failed(self.failed_event(booking))
        handle_payment_failed(self.failed_event(booking))
        self.assertEqual(self.rooms(), 5)

    def test_adventure_spots_are_released_once(self):
        booking = self.book(adventure=True)
        self.assertEqual(self.taken_spots(), 5)
        handle_payment_failed(self.failed_event(booking))
        handle_payment_failed(self.failed_event(booking))
        self.assertEqual(self.taken_spots(), 3)
        self.assertEqual(self.status_of(booking), "CANCELLED")

    def test_vehicle_is_freed_but_a_duplicate_never_frees_it_from_a_newer_booking(self):
        first = self.book(vehicle=True)
        self.assertFalse(self.vehicle_free())
        handle_payment_failed(self.failed_event(first))
        self.assertTrue(self.vehicle_free())
        second = self.book(user=self.user2, vehicle=True)
        self.assertFalse(self.vehicle_free())
        handle_payment_failed(self.failed_event(first))  # duplicate delivery
        self.assertFalse(self.vehicle_free())
        self.assertEqual(self.status_of(second), "PENDING")

    def test_all_item_types_in_one_booking_are_released_together(self):
        booking = self.book(hotel=True, adventure=True, vehicle=True)
        self.assertEqual((self.rooms(), self.taken_spots(), self.vehicle_free()), (4, 5, False))
        handle_payment_failed(self.failed_event(booking))
        self.assertEqual((self.rooms(), self.taken_spots(), self.vehicle_free()), (5, 3, True))

    def test_a_paid_booking_is_neither_cancelled_nor_released(self):
        booking = self.book(hotel=True)
        Booking.objects.filter(pk=booking.pk).update(status="PAID")
        handle_payment_failed(self.failed_event(booking))
        self.assertEqual(self.status_of(booking), "PAID")
        self.assertEqual(self.rooms(), 4)

    def test_user_cancel_then_a_failure_event_does_not_release_twice(self):
        booking = self.book(hotel=True)
        api = APIClient()
        api.force_authenticate(self.user)
        response = api.post(f"/api/v1/bookings/{booking.id}/cancel/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.rooms(), 5)
        handle_payment_failed(self.failed_event(booking))
        self.assertEqual(self.rooms(), 5)
        self.assertEqual(self.status_of(booking), "CANCELLED")

    def test_the_same_ledgered_event_delivered_twice_releases_once(self):
        booking = self.book(hotel=True)
        event = {"event_id": "11111111-1111-4111-8111-111111111111",
                 "booking_id": str(booking.id), "user_id": str(self.user.id),
                 "user_email": self.user.email, "total_amount": str(booking.total_amount)}
        key = f"{TOPIC_PAYMENT_FAILED}:event:{event['event_id']}"
        self.assertTrue(process_event_once(TOPIC_PAYMENT_FAILED, event, key))
        self.assertFalse(process_event_once(TOPIC_PAYMENT_FAILED, event, key))
        self.assertEqual(self.rooms(), 5)


@override_settings(RAZORPAY_WEBHOOK_SECRET=SECRET)
class WebhookToConsumerLifecycleTests(FailureLifecycleBase):
    def test_duplicate_failed_webhook_and_duplicate_consumption_release_once(self):
        booking = self.book(hotel=True)
        self.pay(booking)
        entity = {"id": "pay_F1", "order_id": "order_F1"}
        first = self.webhook("payment.failed", "payment", entity)
        second = self.webhook("payment.failed", "payment", entity)
        self.assertEqual(first.json(), {"status": "ok"})
        self.assertEqual(second.json(), {"status": "duplicate"})
        events = list(OutboxEvent.objects.filter(topic=TOPIC_PAYMENT_FAILED))
        self.assertEqual(len(events), 1)
        self.assertTrue(self.consume(events[0]))
        self.assertFalse(self.consume(events[0]))
        self.assertEqual(self.status_of(booking), "CANCELLED")
        self.assertEqual(Payment.objects.get(booking=booking).status, "FAILED")
        self.assertEqual(self.rooms(), 5)

    def test_late_capture_after_cancellation_records_money_but_never_confirms_or_touches_inventory(self):
        booking = self.book(hotel=True)
        self.pay(booking)
        self.webhook("payment.failed", "payment", {"id": "pay_F1", "order_id": "order_F1"})
        self.consume(OutboxEvent.objects.get(topic=TOPIC_PAYMENT_FAILED))
        self.assertEqual(self.rooms(), 5)

        late = self.webhook("payment.captured", "payment", {"id": "pay_late", "order_id": "order_F1"})
        self.assertEqual(late.json(), {"status": "ok"})
        payment = Payment.objects.get(booking=booking)
        self.assertEqual(payment.status, "SUCCESS")
        self.assertEqual(payment.stripe_payment_intent_id, "pay_late")

        success_events = list(OutboxEvent.objects.filter(topic=TOPIC_PAYMENT_SUCCESS))
        self.assertEqual(len(success_events), 1)
        with patch("apps.bookings.tasks.send_payment_receipt.delay") as receipt:
            with self.assertLogs("apps.kafka_events.consumers", level="ERROR") as logs:
                self.consume(success_events[0])
        receipt.assert_not_called()
        self.assertTrue(any("needs manual review" in line for line in logs.output))
        self.assertEqual(self.status_of(booking), "CANCELLED")
        self.assertEqual(self.rooms(), 5)

    def test_late_verify_after_cancellation_is_refused_and_inventory_is_untouched(self):
        booking = self.book(hotel=True)
        self.pay(booking)
        handle_payment_failed(self.failed_event(booking))
        self.assertEqual(self.rooms(), 5)
        api = APIClient()
        api.force_authenticate(self.user)
        body = {"razorpay_order_id": "order_F1", "razorpay_payment_id": "pay_v",
                "razorpay_signature": "sig", "booking_id": str(booking.id)}
        with patch("apps.payments.views.RazorpayService.verify_payment", return_value=True):
            response = api.post(VERIFY_URL, body, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.status_of(booking), "CANCELLED")
        self.assertEqual(self.rooms(), 5)
        self.assertEqual(Payment.objects.get(booking=booking).status, "SUCCESS")