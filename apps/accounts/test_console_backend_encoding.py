"""
Regression test for the UnicodeEncodeError in RegisterView / ResendOTPView
(apps/accounts/views.py), confirmed to originate from the globe emoji in the
verification email body being written to a Windows cp1252 console stream by
Django's console EmailBackend.

Design notes (why these four tests, not just one):
  1. test_fix_is_applied_to_the_real_streams reads back django.conf.settings-
     triggered state on the actual sys.stdout/sys.stderr used by this process,
     proving the settings.py code ran against the real streams - not a
     reimplementation of the fix inside the test.
  2. test_control_without_fix_still_crashes is a characterization test: it
     proves this test suite can actually detect the original bug, using a
     strict-errors cp1252-like stream with no workaround applied. If this
     test ever stops failing-as-expected, the other tests have lost their
     meaning.
  3. test_registration_succeeds_on_simulated_windows_console exercises the
     real RegisterView end-to-end (not a mocked send_mail) with a cp1252-like
     stream standing in for the Windows console, and checks the full
     application contract: 201, persisted active=False user, and a
     verification record with a usable OTP.
  4. Rollback-on-email-failure is already covered by
     apps/accounts/test_otp_hardening.py::test_email_failure_rolls_back_account_and_hides_details
     and is not duplicated here.
"""
import io
import sys
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import EmailVerification

REGISTER_URL = "/api/v1/auth/register/"
EMOJI = "\U0001F30D"  # same character as views.py's "Welcome to TravelX! <globe>"


class Cp1252LikeStream(io.TextIOWrapper):
    """Stands in for a Windows console using the cp1252 code page: raises on
    any character cp1252 cannot represent, unless reconfigured."""
    def __init__(self, errors='strict'):
        super().__init__(io.BytesIO(), encoding='cp1252', errors=errors)


class ConsoleBackendEncodingTests(TestCase):
    def test_fix_is_applied_to_the_real_streams(self):
        # Proves settings.py actually ran the reconfigure against the process's
        # real stdout/stderr, not just that a block of text exists in the file.
        self.assertEqual(getattr(sys.stdout, 'errors', None), 'backslashreplace')
        self.assertEqual(getattr(sys.stderr, 'errors', None), 'backslashreplace')

    def test_control_without_fix_still_crashes(self):
        # Characterization test: confirms this suite can detect the real bug.
        broken_stream = Cp1252LikeStream(errors='strict')
        with self.assertRaises(UnicodeEncodeError):
            broken_stream.write("Welcome to TravelX! " + EMOJI)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend')
    def test_registration_succeeds_on_simulated_windows_console(self):
        fixed_stream = Cp1252LikeStream(errors='strict')
        fixed_stream.reconfigure(errors='backslashreplace')  # the fix, applied to this stream
        with patch('sys.stdout', fixed_stream):
            client = APIClient()
            resp = client.post(REGISTER_URL, {
                "username": "cp1252_sim_user",
                "email": "cp1252_sim@example.com",
                "password": "StrongPass123",
            }, format="json")
        self.assertEqual(resp.status_code, 201, msg=resp.data)
        from django.contrib.auth.models import User
        user = User.objects.get(username="cp1252_sim_user")
        self.assertFalse(user.is_active)
        verification = EmailVerification.objects.get(user=user)
        self.assertTrue(verification.otp)
