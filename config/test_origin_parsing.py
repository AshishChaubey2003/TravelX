"""
CORS/CSRF origin parsing regression tests (same defect class as the merged
ALLOWED_HOSTS fix): a bare .split(',') kept whitespace on origins, so a space
after a comma made django-cors-headers never match the browser Origin header.
"""
from decouple import Csv
from django.conf import settings
from django.test import SimpleTestCase


class OriginCsvParsingTests(SimpleTestCase):
    def test_csv_strips_whitespace_on_each_origin(self):
        parsed = Csv()('http://localhost:3000, https://travelx-frontend-git-main-x.vercel.app')
        self.assertEqual(parsed, ['http://localhost:3000', 'https://travelx-frontend-git-main-x.vercel.app'])

    def test_loaded_cors_origins_have_no_surrounding_whitespace(self):
        for origin in settings.CORS_ALLOWED_ORIGINS:
            self.assertEqual(origin, origin.strip())
            self.assertNotEqual(origin, '')

    def test_loaded_csrf_trusted_origins_have_no_surrounding_whitespace(self):
        for origin in settings.CSRF_TRUSTED_ORIGINS:
            self.assertEqual(origin, origin.strip())
            self.assertNotEqual(origin, '')

    def test_no_wildcard_origin_configured(self):
        self.assertNotIn('*', settings.CORS_ALLOWED_ORIGINS)
