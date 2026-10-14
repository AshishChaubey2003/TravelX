"""
Batch 3 / Stage D regression tests: receipt-vs-commit race (R3), refund webhook lifecycle,
refund initiation failure, and repeated verify. No gateway or broker is contacted: webhooks are
signed locally and the Razorpay calls are patched. SQLite makes select_for_update() a no-op, so
these prove the once-only logic, not row-lock concurrency (needs PostgreSQL).
"""
import hashlib
import hmac
import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.bookings.models import Booking, EmailNotification
from apps.bookings.services import BookingService
from apps.bookings.tasks import (
    RETRYABLE_EXCEPTIONS, ReceiptNotYetVisible, send_payment_receipt,
)
from apps.hotels.models import Hotel
from apps.kafka_events.consumers import handle_payment_failed
from apps.kafka_events.models import OutboxEvent
from apps.kafka_events.topics import TOPIC_PAYMENT_SUCCESS
from apps.locations.models import City
from apps.payments.models import Payment

SECRET = "whsec_batch3_stage_d_secret"
WEBHOOK_URL = "/api/v1/payments/razorpay/webhook/"
VERIFY_URL = "/api/v1/payments/razorpay/verify/"
REFUND_URL = "/api/v1/payments/refund/"


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pl_user", email="pl@example.com", password="x")
        city = City.objects.create(name="PL City", state="S", latitude="12.9", longitude="77.5")
        self.hotel = Hotel.objects.create(
            city=city, name="H", description="d", price_per_night=Decimal("1000.00"),
            total_rooms=10, available_rooms=5, latitude="12.9", longitude="77.5", is_active=True)

    def book(self, status="PENDING"):
        booking = BookingService.create_booking(
            self.user, {"check_in": date(2030, 1, 1), "check_out": date(2030, 1, 3),
                        "hotel_id": self.hotel.id})
        if status != "PENDING":
            Booking.objects.filter(pk=booking.pk).update(status=status)
        return Booking.objects.get(pk=booking.pk)

    def pay(self, booking, status="SUCCESS", order="order_L1", intent="pay_L1"):
        return Payment.objects.create(
            booking=booking, amount=booking.total_amount, currency="inr", status=status,
            stripe_session_id=order, stripe_payment_intent_id=intent)

    def rooms(self):
        return Hotel.objects.get(pk=self.hotel.pk).available_rooms

    def status_of(self, booking):
        return Booking.objects.get(pk=booking.pk).status

    def pay_status(self, booking):
        return Payment.objects.get(booking=booking).status


class ReceiptRaceTests(Base):
    def test_success_payment_with_booking_not_yet_paid_is_retried_not_skipped(self):
        booking = self.book()
        self.pay(booking)
        with self.assertRaises(ReceiptNotYetVisible):
            send_payment_receipt(str(booking.id))
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(EmailNotification.objects.count(), 0)

    def test_once_the_booking_is_paid_the_receipt_is_sent_exactly_once(self):
        booking = self.book()
        self.pay(booking)
        with self.assertRaises(ReceiptNotYetVisible):
            send_payment_receipt(str(booking.id))
        Booking.objects.filter(pk=booking.pk).update(status="PAID")
        self.assertEqual(send_payment_receipt(str(booking.id)), "sent")
        self.assertEqual(send_payment_receipt(str(booking.id)), "skipped:already-sent")
        self.assertEqual(len(mail.outbox), 1)

    def test_the_retry_exception_is_inside_the_celery_retry_set(self):
        self.assertTrue(issubclass(ReceiptNotYetVisible, RETRYABLE_EXCEPTIONS))
        self.assertTrue(issubclass(ReceiptNotYetVisible, tuple(send_payment_receipt.autoretry_for)))

    def test_unpaid_booking_without_a_success_payment_is_still_skipped(self):
        booking = self.book()
        self.assertEqual(send_payment_receipt(str(booking.id)), "skipped:not-paid")
        self.pay(booking, status="PENDING")
        self.assertEqual(send_payment_receipt(str(booking.id)), "skipped:not-paid")
        self.assertEqual(len(mail.outbox), 0)

    def test_cancelled_booking_with_a_success_payment_is_skipped_not_retried(self):
        booking = self.book(status="CANCELLED")
        self.pay(booking)
        self.assertEqual(send_payment_receipt(str(booking.id)), "skipped:not-paid")
        self.assertEqual(len(mail.outbox), 0)


@override_settings(RAZORPAY_WEBHOOK_SECRET=SECRET)
class RefundLifecycleTests(Base):
    def webhook(self, event, kind, entity, event_id):
        body = json.dumps({"event": event, "payload": {kind: {"entity": entity}}},
                          sort_keys=True).encode()
        sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(WEBHOOK_URL, data=body, content_type="application/json",
                                HTTP_X_RAZORPAY_SIGNATURE=sig, HTTP_X_RAZORPAY_EVENT_ID=event_id)

    def paid(self, payment_status="SUCCESS"):
        booking = self.book(status="PAID")
        self.pay(booking, status=payment_status)
        return booking

    def test_refund_processed_cancels_restores_once_and_repeats_add_nothing(self):
        booking = self.paid()
        self.assertEqual(self.rooms(), 4)
        entity = {"id": "rfnd_1", "payment_id": "pay_L1"}
        self.assertEqual(self.webhook("refund.processed", "refund", entity, "evt_r1").json(), {"status": "ok"})
        self.assertEqual((self.rooms(), self.status_of(booking), self.pay_status(booking)),
                         (5, "CANCELLED", "REFUNDED"))
        same = self.webhook("refund.processed", "refund", entity, "evt_r1")
        self.assertEqual(same.json(), {"status": "duplicate"})
        resent = self.webhook("refund.processed", "refund", entity, "evt_r2")
        self.assertEqual(resent.json(), {"status": "ignored"})
        self.assertEqual(self.rooms(), 5)

    def test_late_payment_failed_after_a_refund_changes_nothing(self):
        booking = self.paid()
        self.webhook("refund.processed", "refund", {"id": "rfnd_1", "payment_id": "pay_L1"}, "evt_r1")
        late = self.webhook("payment.failed", "payment",
                            {"id": "pay_L1", "order_id": "order_L1"}, "evt_f1")
        self.assertEqual(late.json(), {"status": "ignored"})
        handle_payment_failed({"booking_id": str(booking.id)})
        self.assertEqual((self.rooms(), self.status_of(booking), self.pay_status(booking)),
                         (5, "CANCELLED", "REFUNDED"))

    def test_refund_failed_restores_the_payment_and_leaves_booking_and_inventory(self):
        booking = self.paid(payment_status="REFUND_PENDING")
        result = self.webhook("refund.failed", "refund", {"id": "rfnd_1", "payment_id": "pay_L1"}, "evt_rf")
        self.assertEqual(result.json(), {"status": "ok"})
        self.assertEqual((self.rooms(), self.status_of(booking), self.pay_status(booking)),
                         (4, "PAID", "SUCCESS"))

    def test_refund_initiation_failure_changes_neither_booking_payment_nor_inventory(self):
        booking = self.paid()
        api = APIClient()
        api.force_authenticate(self.user)
        with patch("apps.payments.views.RazorpayService.initiate_refund",
                   side_effect=ValueError("Refund could not be initiated")):
            response = api.post(REFUND_URL, {"booking_id": str(booking.id)}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual((self.rooms(), self.status_of(booking), self.pay_status(booking)),
                         (4, "PAID", "SUCCESS"))


@override_settings(RAZORPAY_WEBHOOK_SECRET=SECRET)
class RepeatedVerifyTests(Base):
    def verify(self, booking):
        api = APIClient()
        api.force_authenticate(self.user)
        body = {"razorpay_order_id": "order_L1", "razorpay_payment_id": "pay_L1",
                "razorpay_signature": "sig", "booking_id": str(booking.id)}
        with patch("apps.payments.views.RazorpayService.verify_payment", return_value=True):
            return api.post(VERIFY_URL, body, format="json")

    def test_verifying_twice_pays_once_and_emits_one_success_event(self):
        booking = self.book()
        self.pay(booking, status="PENDING", intent=None)
        self.assertEqual(self.verify(booking).status_code, 200)
        self.assertEqual(self.verify(booking).status_code, 200)
        self.assertEqual((self.status_of(booking), self.pay_status(booking), self.rooms()),
                         ("PAID", "SUCCESS", 4))
        self.assertEqual(OutboxEvent.objects.filter(topic=TOPIC_PAYMENT_SUCCESS).count(), 1)

    def test_a_webhook_capture_after_verify_adds_no_second_success_event(self):
        booking = self.book()
        self.pay(booking, status="PENDING", intent=None)
        self.verify(booking)
        body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {
            "id": "pay_L1", "order_id": "order_L1"}}}}, sort_keys=True).encode()
        sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        response = self.client.post(WEBHOOK_URL, data=body, content_type="application/json",
                                    HTTP_X_RAZORPAY_SIGNATURE=sig, HTTP_X_RAZORPAY_EVENT_ID="evt_c")
        self.assertEqual(response.json(), {"status": "ignored"})
        self.assertEqual(OutboxEvent.objects.filter(topic=TOPIC_PAYMENT_SUCCESS).count(), 1)
        self.assertEqual(self.status_of(booking), "PAID")