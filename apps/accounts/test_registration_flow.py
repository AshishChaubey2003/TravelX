"""
Batch 1 regression tests: registration + OTP success and error paths.
All tests assert CURRENT, correct behaviour and must pass as-is.
Email is captured with the locmem backend; no real mail is sent.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import EmailVerification

REGISTER_URL = "/api/v1/auth/register/"
VERIFY_URL = "/api/v1/auth/verify-otp/"
RESEND_URL = "/api/v1/auth/resend-otp/"
LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


@override_settings(EMAIL_BACKEND=LOCMEM)
class RegistrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()

    def test_register_creates_inactive_user_and_sends_one_otp_email(self):
        resp = self.client.post(REGISTER_URL, {
            "username": "reg_ok", "email": "reg_ok@example.com", "password": "pw12345!",
        }, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertIn("email", resp.data)
        user = User.objects.get(username="reg_ok")
        self.assertFalse(user.is_active)
        self.assertTrue(EmailVerification.objects.filter(user=user).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["reg_ok@example.com"])
        self.assertIn("Verify Your Email", mail.outbox[0].subject)

    def test_register_duplicate_email_is_rejected(self):
        User.objects.create_user(username="existing", email="dup@example.com", password="x")
        resp = self.client.post(REGISTER_URL, {
            "username": "second", "email": "dup@example.com", "password": "pw12345!",
        }, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(User.objects.filter(username="second").exists())
        self.assertEqual(len(mail.outbox), 0)


@override_settings(EMAIL_BACKEND=LOCMEM)
class VerifyOTPTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()
        self.user = User.objects.create_user(
            username="verify_user", email="verify@example.com",
            password="pw12345!", is_active=False,
        )
        self.verification = EmailVerification.objects.create(user=self.user)
        self.otp = self.verification.generate_otp()

    def test_correct_otp_activates_user(self):
        resp = self.client.post(VERIFY_URL, {"email": self.user.email, "otp": self.otp}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.verification.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertTrue(self.verification.is_verified)

    def test_wrong_otp_is_rejected(self):
        wrong = "000000" if self.otp != "000000" else "111111"
        resp = self.client.post(VERIFY_URL, {"email": self.user.email, "otp": wrong}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_expired_otp_is_rejected(self):
        self.verification.expires_at = timezone.now() - timedelta(minutes=1)
        self.verification.save(update_fields=["expires_at"])
        resp = self.client.post(VERIFY_URL, {"email": self.user.email, "otp": self.otp}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_already_verified_returns_ok(self):
        self.verification.is_verified = True
        self.verification.save(update_fields=["is_verified"])
        resp = self.client.post(VERIFY_URL, {"email": self.user.email, "otp": "123456"}, format="json")
        self.assertEqual(resp.status_code, 200)

    def test_unknown_email_returns_404(self):
        resp = self.client.post(VERIFY_URL, {"email": "nobody@example.com", "otp": "123456"}, format="json")
        self.assertEqual(resp.status_code, 404)


@override_settings(EMAIL_BACKEND=LOCMEM)
class ResendOTPTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()
        self.user = User.objects.create_user(
            username="resend_user", email="resend@example.com",
            password="pw12345!", is_active=False,
        )
        self.verification = EmailVerification.objects.create(user=self.user)
        self.verification.generate_otp()

    def test_resend_sends_new_otp_to_inactive_user(self):
        resp = self.client.post(RESEND_URL, {"email": self.user.email}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("New OTP", mail.outbox[0].subject)

    def test_resend_unknown_or_active_user_returns_404(self):
        resp = self.client.post(RESEND_URL, {"email": "ghost@example.com"}, format="json")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(len(mail.outbox), 0)