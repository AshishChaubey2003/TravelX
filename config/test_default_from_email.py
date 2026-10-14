from django.conf import settings
from django.test import SimpleTestCase


class DefaultFromEmailTests(SimpleTestCase):
    def test_default_from_email_is_configured_not_django_fallback(self):
        # Django's built-in fallback is 'webmaster@localhost'; accounts OTP mails and booking
        # receipts use settings.DEFAULT_FROM_EMAIL, so the project must define its own sender.
        self.assertNotEqual(settings.DEFAULT_FROM_EMAIL, 'webmaster@localhost')
        self.assertIn('@', settings.DEFAULT_FROM_EMAIL)