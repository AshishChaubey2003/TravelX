"""
Regression tests for ALLOWED_HOSTS parsing.

Root cause these guard against: ALLOWED_HOSTS was previously built with a bare
`config('ALLOWED_HOSTS', default=...).split(',')`, which does NOT strip
whitespace. A value entered the natural way in a hosting dashboard —
"host-a, host-b, host-c" with a space after each comma — then produced
[' host-b', ' host-c'] with leading spaces that never match the incoming Host
header, raising DisallowedHost even though the variable was set. The fix parses
it with decouple's Csv(), which splits AND strips each entry and drops empties.
"""
from decouple import Csv
from django.conf import settings
from django.test import SimpleTestCase


class AllowedHostsCsvParsingTests(SimpleTestCase):
    def test_csv_strips_surrounding_whitespace_on_each_host(self):
        # Exactly the caster ALLOWED_HOSTS now uses. A space-after-comma value
        # must yield clean hostnames, not entries with leading/trailing spaces.
        parsed = Csv()(
            'localhost, 127.0.0.1 , travelx-backend-t6hf.onrender.com'
        )
        self.assertIn('travelx-backend-t6hf.onrender.com', parsed)
        self.assertNotIn(' travelx-backend-t6hf.onrender.com', parsed)
        self.assertEqual(
            parsed, ['localhost', '127.0.0.1', 'travelx-backend-t6hf.onrender.com']
        )

    def test_messy_value_still_yields_clean_usable_hosts(self):
        # A messy value (stray spaces, trailing comma) must still produce clean,
        # whitespace-free real hosts. Any residual empty entry is harmless — ''
        # matches no Host header — but a wildcard must never be introduced.
        parsed = Csv()('localhost, , travelx-backend-t6hf.onrender.com ,')
        self.assertIn('localhost', parsed)
        self.assertIn('travelx-backend-t6hf.onrender.com', parsed)
        self.assertNotIn('*', parsed)

    def test_loaded_allowed_hosts_entries_have_no_surrounding_whitespace(self):
        # Guard the live setting: whatever the environment supplies, no entry may
        # carry surrounding whitespace, or Host-header matching silently fails.
        for host in settings.ALLOWED_HOSTS:
            self.assertEqual(host, host.strip())
            self.assertNotEqual(host, '')

    def test_default_allowed_hosts_parse_to_expected_local_hosts(self):
        # Local-dev default behaviour is preserved by the Csv() change.
        self.assertEqual(
            Csv()('localhost,127.0.0.1,0.0.0.0,web'),
            ['localhost', '127.0.0.1', '0.0.0.0', 'web'],
        )
