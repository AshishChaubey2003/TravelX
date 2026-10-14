"""
Batch 1 regression tests: Razorpay webhook signature, captured/failed events,
duplicates, unknown events and malformed payloads. All assert CURRENT, correct
behaviour and must pass as-is. The real HMAC path is exercised with a test
RAZORPAY_WEBHOOK_SECRET; no live Razorpay call is made.
"""
import hashlib
import hmac
import json
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.bookings.models import Booking
from apps.kafka_events.models import OutboxEvent
from apps.kafka_events.topics import TOPIC_PAYMENT_SUCCESS, TOPIC_PAYMENT_FAILED
from apps.payments.models import Payment
from apps.payments.webhooks import RazorpayWebhookView

SECRET = "whsec_batch1_test_secret"


@override_settings(RAZORPAY_WEBHOOK_SECRET=SECRET)
class RazorpayWebhookEventTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(username="wh_user", email="wh@example.com", password="x")
        self.booking = Booking.objects.create(
            user=self.user, status="PENDING", total_amount=Decimal("1000.00"),
            check_in=date(2030, 1, 1), check_out=date(2030, 1, 3),
        )
        self.payment = Payment.objects.create(
            booking=self.booking, stripe_session_id="order_x",
            amount=Decimal("1000.00"), status="PENDING",
        )

    def _sign(self, raw_bytes):
        return hmac.new(SECRET.encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()

    def _post(self, payload, event_id="evt_1", signature=None, sign=True, raw_override=None):
        raw = raw_override if raw_override is not None else json.dumps(payload)
        raw_bytes = raw.encode("utf-8")
        headers = {"HTTP_X_RAZORPAY_EVENT_ID": event_id}
        if sign:
            headers["HTTP_X_RAZORPAY_SIGNATURE"] = signature if signature is not None else self._sign(raw_bytes)
        elif signature is not None:
            headers["HTTP_X_RAZORPAY_SIGNATURE"] = signature
        request = self.factory.post(
            "/api/v1/payments/razorpay/webhook/",
            data=raw, content_type="application/json", **headers,
        )
        return RazorpayWebhookView.as_view()(request)

    def _captured(self):
        return {"event": "payment.captured", "created_at": 1,
                "payload": {"payment": {"entity": {"id": "pay_x", "order_id": "order_x"}}}}

    def _failed(self):
        return {"event": "payment.failed", "created_at": 1,
                "payload": {"payment": {"entity": {"id": "pay_x", "order_id": "order_x"}}}}

    # --- signature ---
    def test_missing_signature_is_401(self):
        resp = self._post(self._captured(), sign=False)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "PENDING")

    def test_invalid_signature_is_401(self):
        resp = self._post(self._captured(), signature="deadbeef", sign=False)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "PENDING")

    # --- payment.captured ---
    def test_captured_marks_success_and_enqueues_event(self):
        resp = self._post(self._captured(), event_id="evt_cap")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "SUCCESS")
        self.assertEqual(OutboxEvent.objects.filter(topic=TOPIC_PAYMENT_SUCCESS).count(), 1)

    def test_duplicate_captured_is_ignored(self):
        first = self._post(self._captured(), event_id="evt_dup")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        second = self._post(self._captured(), event_id="evt_dup")
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data.get("status"), "duplicate")
        self.assertEqual(OutboxEvent.objects.filter(topic=TOPIC_PAYMENT_SUCCESS).count(), 1)

    # --- payment.failed ---
    def test_failed_marks_failed_and_enqueues_event(self):
        resp = self._post(self._failed(), event_id="evt_fail")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "FAILED")
        self.assertEqual(OutboxEvent.objects.filter(topic=TOPIC_PAYMENT_FAILED).count(), 1)

    # --- unknown + malformed ---
    def test_unknown_event_type_is_ignored_200(self):
        resp = self._post({"event": "order.paid", "payload": {}}, event_id="evt_unk")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "PENDING")

    def test_malformed_body_is_400(self):
        resp = self._post(None, raw_override="not-json{", event_id="evt_bad")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_payload_not_object_is_400(self):
        resp = self._post(None, raw_override="[]", event_id="evt_arr")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_event_type_is_400(self):
        resp = self._post({"foo": "bar"}, event_id="evt_noevt")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_handled_event_without_entity_is_400(self):
        resp = self._post({"event": "payment.captured", "payload": {}}, event_id="evt_noent")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)