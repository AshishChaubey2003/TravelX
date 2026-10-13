"""
Batch 2 regression tests: accounts / OTP hardening.

Covers registration email failure, case-insensitive duplicate email, missing verification
records, malformed / invalid / expired OTPs, already-verified policy, resend failure state,
throttling, secure OTP generation and log hygiene. Email uses the locmem backend and the
SMTP layer is mocked, so no real mail or network is used.
"""
import re
import secrets
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts import models as accounts_models
from apps.accounts.models import EmailVerification

REGISTER_URL = "/api/v1/auth/register/"
VERIFY_URL = "/api/v1/auth/verify-otp/"
RESEND_URL = "/api/v1/auth/resend-otp/"
LOCMEM = "django.core.mail.backends.locmem.EmailBackend"
OPEN_RATES = {"otp_verify": "1000/min", "otp_resend": "1000/min"}
PASSWORD = "S3cretPw!99"
LEAK = "535 auth failed password=LeakedSmtpPw host=smtp.internal.example"
OTP_IN_BODY = re.compile(r"OTP is: (\d{6})")
LEAK_MARKERS = ("LeakedSmtpPw", "smtp.internal.example", "535")


class AccountsTestBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()

    def pending_user(self, username="pending", email="pending@example.com",
                     with_record=True, otp="654321"):
        user = User.objects.create_user(
            username=username, email=email, password=PASSWORD, is_active=False,
        )
        verification = None
        if with_record:
            verification = EmailVerification.objects.create(user=user)
            verification.generate_otp()
            EmailVerification.objects.filter(pk=verification.pk).update(otp=otp)
            verification.refresh_from_db()
        return user, verification

    def verify(self, **payload):
        return self.client.post(VERIFY_URL, payload, format="json")

    def resend(self, **payload):
        return self.client.post(RESEND_URL, payload, format="json")

    def assert_log_hygiene(self, logs, *forbidden):
        """No secret text in the log output and no traceback / exception text attached."""
        joined = "\n".join(logs.output)
        for text in forbidden:
            self.assertNotIn(text, joined)
        for record in logs.records:
            self.assertIsNone(record.exc_info)
            self.assertIsNone(record.exc_text)
        return joined


@override_settings(EMAIL_BACKEND=LOCMEM)
class RegistrationHardeningTests(AccountsTestBase):
    PAYLOAD = {"username": "hard_reg", "email": "hard.reg@example.com", "password": PASSWORD}

    def test_success_sends_otp_matching_stored_and_never_returns_it(self):
        resp = self.client.post(REGISTER_URL, self.PAYLOAD, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        match = OTP_IN_BODY.search(body)
        self.assertIsNotNone(match)
        stored = EmailVerification.objects.get(user__username="hard_reg").otp
        self.assertEqual(match.group(1), stored)
        self.assertNotIn(stored, str(resp.data))
        self.assertNotIn(PASSWORD, body)
        self.assertFalse(User.objects.get(username="hard_reg").is_active)

    def test_email_failure_rolls_back_account_and_hides_details(self):
        with patch("apps.accounts.models.secrets.randbelow", return_value=424242):
            with patch("apps.accounts.views.send_mail", side_effect=OSError(LEAK)) as send:
                with self.assertLogs("travelx.request", level="ERROR") as logs:
                    resp = self.client.post(REGISTER_URL, self.PAYLOAD, format="json")
        self.assertEqual(resp.status_code, 500)
        for marker in LEAK_MARKERS:
            self.assertNotIn(marker, str(resp.data))
        self.assertFalse(User.objects.filter(username="hard_reg").exists())
        self.assertFalse(EmailVerification.objects.exists())
        # The OTP really was in the (failed) message, so its absence from logs is meaningful.
        self.assertIn("424242", send.call_args.kwargs["message"])
        joined = self.assert_log_hygiene(logs, PASSWORD, "424242", *LEAK_MARKERS)
        self.assertIn("RegisterView", joined)
        self.assertIn("error_type=OSError", joined)
        self.assertNotIn("user_id=None", joined)

    def test_duplicate_email_is_case_insensitive(self):
        User.objects.create_user(username="orig", email="Mixed.Case@example.com", password="x")
        for index, email in enumerate(("mixed.case@example.com", "MIXED.CASE@EXAMPLE.COM")):
            with self.subTest(email=email):
                resp = self.client.post(REGISTER_URL, {
                    "username": f"dup_{index}", "email": email, "password": PASSWORD,
                }, format="json")
                self.assertEqual(resp.status_code, 400)
                self.assertIn("email", resp.data)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(EMAIL_BACKEND=LOCMEM)
@patch.dict(ScopedRateThrottle.THROTTLE_RATES, OPEN_RATES)
class VerifyHardeningTests(AccountsTestBase):
    def test_missing_record_for_inactive_user_is_404_not_500(self):
        user, _ = self.pending_user(with_record=False)
        resp = self.verify(email=user.email, otp="123456")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("error", resp.data)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_missing_record_for_active_user_reports_already_verified(self):
        User.objects.create_user(username="active", email="active@example.com", password=PASSWORD)
        resp = self.verify(email="active@example.com", otp="123456")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("already verified", resp.data["message"])

    def test_malformed_otps_are_rejected_without_activation(self):
        user, verification = self.pending_user()
        email = user.email
        payloads = {
            "non-digit": {"email": email, "otp": "abcdef"},
            "too long": {"email": email, "otp": "12345678"},
            "too short": {"email": email, "otp": "12345"},
            "blank": {"email": email, "otp": ""},
            "null": {"email": email, "otp": None},
            "missing": {"email": email},
            "list": {"email": email, "otp": ["654321"]},
            "object": {"email": email, "otp": {"a": 1}},
        }
        for label, payload in payloads.items():
            with self.subTest(label):
                resp = self.client.post(VERIFY_URL, payload, format="json")
                self.assertEqual(resp.status_code, 400)
        user.refresh_from_db()
        verification.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(verification.is_verified)

    def test_non_ascii_otp_is_a_clean_400(self):
        user, _ = self.pending_user()
        resp = self.verify(email=user.email, otp="\u0663\u0664\u0665\u0666\u0667\u0668")
        self.assertEqual(resp.status_code, 400)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_email_lookup_is_case_insensitive(self):
        user, _ = self.pending_user(email="case.verify@example.com")
        resp = self.verify(email="CASE.VERIFY@EXAMPLE.COM", otp="654321")
        self.assertEqual(resp.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_otp_comparison_is_constant_time(self):
        user, _ = self.pending_user()
        with patch("apps.accounts.views.secrets.compare_digest",
                   wraps=secrets.compare_digest) as compare:
            resp = self.verify(email=user.email, otp="000000")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(compare.called)

    def test_activation_happens_only_after_valid_otp_and_otp_is_single_use(self):
        user, verification = self.pending_user()
        self.assertEqual(self.verify(email=user.email, otp="111111").status_code, 400)
        user.refresh_from_db()
        verification.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(verification.is_verified)
        self.assertEqual(verification.otp, "654321")

        self.assertEqual(self.verify(email=user.email, otp="654321").status_code, 200)
        user.refresh_from_db()
        verification.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(verification.is_verified)
        self.assertEqual(verification.otp, "")

        replay = self.verify(email=user.email, otp="654321")
        self.assertEqual(replay.status_code, 200)
        self.assertIn("already verified", replay.data["message"])

    def test_expired_correct_otp_leaves_state_untouched(self):
        user, verification = self.pending_user()
        EmailVerification.objects.filter(pk=verification.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1))
        resp = self.verify(email=user.email, otp="654321")
        self.assertEqual(resp.status_code, 400)
        user.refresh_from_db()
        verification.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(verification.is_verified)
        self.assertEqual(verification.otp, "654321")

    def test_already_verified_policy(self):
        # Policy: input validation runs first, then account state. A well-formed OTP for an
        # already-verified user gets 200; a malformed OTP gets 400 whatever the state is.
        user, verification = self.pending_user()
        EmailVerification.objects.filter(pk=verification.pk).update(is_verified=True)
        ok = self.verify(email=user.email, otp="999999")
        self.assertEqual(ok.status_code, 200)
        self.assertIn("already verified", ok.data["message"])
        malformed = self.verify(email=user.email, otp="12345678")
        self.assertEqual(malformed.status_code, 400)

    def test_legacy_case_variant_duplicates_do_not_crash_and_pick_pending_account(self):
        User.objects.create_user(username="lowerdup", email="dup@example.com", password=PASSWORD)
        pending, _ = self.pending_user(username="upperdup", email="DUP@example.com")
        resp = self.verify(email="dup@example.com", otp="654321")
        self.assertEqual(resp.status_code, 200)
        pending.refresh_from_db()
        self.assertTrue(pending.is_active)


@override_settings(EMAIL_BACKEND=LOCMEM)
@patch.dict(ScopedRateThrottle.THROTTLE_RATES, OPEN_RATES)
class ResendHardeningTests(AccountsTestBase):
    def test_missing_record_is_created_and_otp_sent(self):
        user, _ = self.pending_user(with_record=False)
        resp = self.resend(email=user.email)
        self.assertEqual(resp.status_code, 200)
        stored = EmailVerification.objects.get(user=user).otp
        self.assertEqual(len(mail.outbox), 1)
        match = OTP_IN_BODY.search(mail.outbox[0].body)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), stored)

    def test_resend_refreshes_expiry_and_emails_the_stored_address(self):
        user, verification = self.pending_user(email="resend.case@example.com")
        EmailVerification.objects.filter(pk=verification.pk).update(
            expires_at=timezone.now() - timedelta(minutes=5))
        resp = self.resend(email="RESEND.CASE@EXAMPLE.COM")
        self.assertEqual(resp.status_code, 200)
        verification.refresh_from_db()
        self.assertGreater(verification.expires_at, timezone.now() + timedelta(minutes=9))
        self.assertEqual(mail.outbox[0].to, [user.email])
        self.assertEqual(OTP_IN_BODY.search(mail.outbox[0].body).group(1), verification.otp)

    def test_email_failure_keeps_previous_otp_valid_and_hides_details(self):
        user, verification = self.pending_user()
        old_expiry = verification.expires_at
        with patch("apps.accounts.models.secrets.randbelow", return_value=123456):
            with patch("apps.accounts.views.send_mail", side_effect=OSError(LEAK)) as send:
                with self.assertLogs("travelx.request", level="ERROR") as logs:
                    resp = self.resend(email=user.email)
        self.assertEqual(resp.status_code, 500)
        for marker in LEAK_MARKERS:
            self.assertNotIn(marker, str(resp.data))
        self.assertIn("123456", send.call_args.kwargs["message"])
        joined = self.assert_log_hygiene(logs, "123456", "654321", *LEAK_MARKERS)
        self.assertIn("ResendOTPView", joined)
        self.assertIn("error_type=OSError", joined)
        verification.refresh_from_db()
        self.assertEqual(verification.otp, "654321")
        self.assertEqual(verification.expires_at, old_expiry)
        self.assertFalse(verification.is_verified)
        # The code the user last received still works.
        self.assertEqual(self.verify(email=user.email, otp="654321").status_code, 200)

    def test_malformed_email_input_is_a_clean_400(self):
        payloads = {
            "missing": {},
            "blank": {"email": ""},
            "null": {"email": None},
            "not an email": {"email": "not-an-email"},
            "list": {"email": ["a@example.com"]},
        }
        for label, payload in payloads.items():
            with self.subTest(label):
                resp = self.client.post(RESEND_URL, payload, format="json")
                self.assertEqual(resp.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_verified_but_inactive_account_gets_no_otp(self):
        user, verification = self.pending_user()
        EmailVerification.objects.filter(pk=verification.pk).update(is_verified=True)
        resp = self.resend(email=user.email)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(EMAIL_BACKEND=LOCMEM)
class OTPThrottleHardeningTests(AccountsTestBase):
    @patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"otp_verify": "2/min"})
    def test_malformed_attempts_count_and_block_a_later_correct_otp(self):
        user, _ = self.pending_user()
        for _ in range(2):
            self.assertEqual(self.verify(email=user.email, otp="abcdef").status_code, 400)
        blocked = self.verify(email=user.email, otp="654321")
        self.assertEqual(blocked.status_code, 429)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    @patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"otp_resend": "2/min"})
    def test_failed_sends_still_count_toward_the_resend_throttle(self):
        user, _ = self.pending_user()
        with patch("apps.accounts.views.send_mail", side_effect=OSError(LEAK)) as send:
            with self.assertLogs("travelx.request", level="ERROR"):
                statuses = [self.resend(email=user.email).status_code for _ in range(3)]
        self.assertEqual(statuses, [500, 500, 429])
        self.assertEqual(send.call_count, 2)


class OTPGenerationTests(TestCase):
    def _verification(self):
        user = User.objects.create_user(
            username="gen_user", email="gen@example.com", password=PASSWORD, is_active=False)
        return EmailVerification.objects.create(user=user)

    def test_generate_otp_is_zero_padded_six_digits_from_secrets(self):
        verification = self._verification()
        with patch("apps.accounts.models.secrets.randbelow", return_value=42) as randbelow:
            otp = verification.generate_otp()
        self.assertEqual(otp, "000042")
        randbelow.assert_called_once_with(10 ** 6)
        verification.refresh_from_db()
        self.assertEqual(verification.otp, "000042")
        remaining = (verification.expires_at - timezone.now()).total_seconds()
        self.assertAlmostEqual(remaining, 600, delta=5)

    def test_models_module_no_longer_uses_random(self):
        self.assertFalse(hasattr(accounts_models, "random"))

    def test_generated_otps_are_always_six_digit_strings(self):
        verification = self._verification()
        for _ in range(100):
            otp = verification.generate_otp()
            self.assertRegex(otp, r"^\d{6}$")