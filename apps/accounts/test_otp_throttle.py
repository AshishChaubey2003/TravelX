from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.models import EmailVerification


class OTPVerifyThrottleTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()
        self.user = User.objects.create_user(
            username='throttleuser', email='throttle@example.com',
            password='pw12345!', is_active=False,
        )
        self.verification = EmailVerification.objects.create(user=self.user)
        # F-010: generate_otp() stores only the hash; keep the returned
        # plaintext for requests that need to submit the real code.
        self.plain_otp = self.verification.generate_otp()

    # FIX (F-22 throttle test follow-up): see test_plan_trip.py for the
    # explanation. patch.dict mutates the live, shared THROTTLE_RATES dict
    # and restores it automatically after this test.
    @patch.dict(ScopedRateThrottle.THROTTLE_RATES, {'otp_verify': '2/min'})
    def test_repeated_verify_attempts_are_throttled(self):
        url = '/api/v1/auth/verify-otp/'
        payload = {'email': self.user.email, 'otp': '000000'}  # intentionally wrong
        r1 = self.client.post(url, payload, format='json')
        r2 = self.client.post(url, payload, format='json')
        r3 = self.client.post(url, payload, format='json')
        self.assertEqual(r1.status_code, 400)
        self.assertEqual(r2.status_code, 400)
        self.assertEqual(r3.status_code, 429)

    def test_otp_expiry_and_success_still_work(self):
        cache.clear()
        otp = self.plain_otp
        url = '/api/v1/auth/verify-otp/'
        resp = self.client.post(url, {'email': self.user.email, 'otp': otp}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.verification.refresh_from_db()
        self.assertTrue(self.verification.is_verified)


class OTPResendThrottleTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()
        self.user = User.objects.create_user(
            username='resenduser', email='resend@example.com',
            password='pw12345!', is_active=False,
        )
        EmailVerification.objects.create(user=self.user)

    @patch.dict(ScopedRateThrottle.THROTTLE_RATES, {'otp_resend': '2/min'})
    @patch('apps.accounts.views.send_mail')
    def test_repeated_resend_attempts_are_throttled(self, mock_send_mail):
        url = '/api/v1/auth/resend-otp/'
        payload = {'email': self.user.email}
        r1 = self.client.post(url, payload, format='json')
        r2 = self.client.post(url, payload, format='json')
        r3 = self.client.post(url, payload, format='json')
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r3.status_code, 429)
        self.assertEqual(mock_send_mail.call_count, 2)


class RegistrationErrorHandlingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()

    @patch('apps.accounts.views.send_mail', side_effect=RuntimeError('smtp exploded'))
    def test_registration_email_failure_does_not_leak_exception(self, mock_send_mail):
        url = '/api/v1/auth/register/'
        payload = {'username': 'newbie_f22', 'email': 'newbie_f22@example.com', 'password': 'pw12345!'}
        with self.assertLogs('travelx.request', level='ERROR') as log_ctx:
            resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 500)
        self.assertNotIn('smtp exploded', str(resp.data))
        self.assertTrue(any('RegisterView' in msg for msg in log_ctx.output))
        self.assertFalse(User.objects.filter(username='newbie_f22').exists())