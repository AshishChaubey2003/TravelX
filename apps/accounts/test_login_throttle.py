"""
Regression tests for F-001: login throttling on `/api/v1/auth/token/`.

These tests pass only when the stock simplejwt `TokenObtainPairView` has
been subclassed to attach throttles (apps/accounts/urls.py defines
`ThrottledTokenObtainPairView`). Running them against the pre-Batch-C
baseline FAILS: without the subclass, both scenarios complete all attempts
with 401 (never 429).

Two scenarios exercise the two throttles independently:

- IP throttle (`login`): many bad logins from one IP against random
  usernames -> the N+1-th response is 429.
- Account throttle (`login_account`): many bad logins against the same
  username from DIFFERENT IPs -> the M+1-th response is 429.

We patch the SCOPE RATES at import level with patch.dict so the test uses a
small, fast limit (and the test does not depend on `override_settings`,
which does not reach ScopedRateThrottle.THROTTLE_RATES — same pattern the
project uses for `apps/ai_agent/test_plan_trip.py`).
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle


URL = '/api/v1/auth/token/'


class LoginIPThrottleTests(TestCase):
    """
    The IP-keyed throttle fires after `login` requests, regardless of which
    username is being probed. We use fresh random usernames per request so
    the account-keyed throttle is never the trigger.
    """

    def setUp(self):
        self.client = APIClient()
        cache.clear()

    @patch.dict(ScopedRateThrottle.THROTTLE_RATES, {
        'login': '3/min',
        'login_account': '100/min',   # effectively off for this test
    })
    def test_ip_throttle_blocks_after_limit(self):
        for i in range(3):
            response = self.client.post(
                URL,
                data={'username': f'ghost_{i}', 'password': 'wrong'},
                format='json',
            )
            self.assertIn(response.status_code, (400, 401),
                          f'attempt {i} unexpectedly got {response.status_code}')
        blocked = self.client.post(
            URL,
            data={'username': 'ghost_last', 'password': 'wrong'},
            format='json',
        )
        self.assertEqual(blocked.status_code, 429)


class LoginAccountThrottleTests(TestCase):
    """
    The account-keyed throttle fires after `login_account` requests against
    the SAME username, even when every request comes from a different IP.
    APIClient.credentials() + REMOTE_ADDR lets us simulate the botnet case.
    """

    def setUp(self):
        self.client = APIClient()
        cache.clear()
        # The user exists but we always supply a wrong password: this makes
        # the test exercise login failure, which is the realistic attack
        # shape (also tests that the throttle counts bad attempts, not just
        # the single-success path).
        self.target = User.objects.create_user(
            username='target_user', email='t@example.com', password='correct',
        )

    @patch.dict(ScopedRateThrottle.THROTTLE_RATES, {
        'login': '1000/min',          # effectively off for this test
        'login_account': '3/min',
    })
    def test_account_throttle_blocks_distributed_spraying(self):
        # Each request comes from a different IP so the IP-keyed throttle
        # cannot possibly be the one firing.
        for i in range(3):
            response = self.client.post(
                URL,
                data={'username': 'target_user', 'password': 'wrong'},
                format='json',
                REMOTE_ADDR=f'10.0.0.{i + 1}',
            )
            self.assertEqual(response.status_code, 401,
                             f'attempt {i} unexpectedly got {response.status_code}')
        blocked = self.client.post(
            URL,
            data={'username': 'target_user', 'password': 'wrong'},
            format='json',
            REMOTE_ADDR='10.0.0.99',
        )
        self.assertEqual(blocked.status_code, 429)

    @patch.dict(ScopedRateThrottle.THROTTLE_RATES, {
        'login': '1000/min',
        'login_account': '3/min',
    })
    def test_account_throttle_isolates_different_usernames(self):
        """A throttled attack on user A must not block user B."""
        for i in range(3):
            response = self.client.post(
                URL,
                data={'username': 'target_user', 'password': 'wrong'},
                format='json',
                REMOTE_ADDR=f'10.0.1.{i + 1}',
            )
            self.assertEqual(response.status_code, 401)
        a_blocked = self.client.post(
            URL,
            data={'username': 'target_user', 'password': 'wrong'},
            format='json',
            REMOTE_ADDR='10.0.1.99',
        )
        self.assertEqual(a_blocked.status_code, 429)

        other = self.client.post(
            URL,
            data={'username': 'other_user', 'password': 'wrong'},
            format='json',
            REMOTE_ADDR='10.0.1.100',
        )
        # 'other_user' has never been attempted — the account throttle must
        # NOT fire here. (401 because the account doesn't exist.)
        self.assertEqual(other.status_code, 401)


class AccountThrottleKeyNormalizationTests(TestCase):
    """
    The design of LoginAccountThrottle is to NOT normalise the username
    before using it as a throttle key, so an attacker cannot evade the
    throttle by alternating case or adding whitespace. These tests pin the
    behaviour: 'Target_User' and 'target_user' must count as DIFFERENT keys
    (they are different attack targets as far as simplejwt is concerned),
    and attempts against 'target_user' must NOT be defeated by whitespace
    around the value.
    """

    def setUp(self):
        self.client = APIClient()
        cache.clear()
        User.objects.create_user(
            username='target_user', email='t2@example.com', password='correct',
        )

    @patch.dict(ScopedRateThrottle.THROTTLE_RATES, {
        'login': '1000/min',
        'login_account': '2/min',
    })
    def test_case_variant_is_a_different_throttle_bucket(self):
        """
        Hammering 'target_user' three times fills the bucket for that key.
        An attempt against 'Target_User' with the capital T must start from
        a fresh bucket because the simplejwt auth itself is case-sensitive —
        a username with a different case is a different account to attack.
        """
        for i in range(2):
            r = self.client.post(
                URL,
                data={'username': 'target_user', 'password': 'wrong'},
                format='json',
                REMOTE_ADDR=f'10.1.0.{i + 1}',
            )
            self.assertEqual(r.status_code, 401)
        blocked = self.client.post(
            URL,
            data={'username': 'target_user', 'password': 'wrong'},
            format='json',
            REMOTE_ADDR='10.1.0.9',
        )
        self.assertEqual(blocked.status_code, 429)

        # Case variant uses a different throttle bucket.
        case_variant = self.client.post(
            URL,
            data={'username': 'Target_User', 'password': 'wrong'},
            format='json',
            REMOTE_ADDR='10.1.0.10',
        )
        self.assertEqual(case_variant.status_code, 401,
                         "Case variant should get its own throttle bucket.")

    @patch.dict(ScopedRateThrottle.THROTTLE_RATES, {
        'login': '1000/min',
        'login_account': '2/min',
    })
    def test_whitespace_around_username_still_hits_same_bucket(self):
        """
        Trailing/leading whitespace is NOT a legitimate username variant;
        the throttle strips it so an attacker can't pad the value to evade.
        """
        for i in range(2):
            r = self.client.post(
                URL,
                data={'username': 'target_user', 'password': 'wrong'},
                format='json',
                REMOTE_ADDR=f'10.2.0.{i + 1}',
            )
            self.assertEqual(r.status_code, 401)
        padded = self.client.post(
            URL,
            data={'username': '  target_user  ', 'password': 'wrong'},
            format='json',
            REMOTE_ADDR='10.2.0.9',
        )
        self.assertEqual(padded.status_code, 429,
                         "Whitespace padding should hit the same throttle bucket.")

    @patch.dict(ScopedRateThrottle.THROTTLE_RATES, {
        'login': '1000/min',
        'login_account': '2/min',
    })
    def test_missing_username_falls_back_to_ip(self):
        """
        A payload with no username field must not evade the throttle.
        LoginAccountThrottle falls back to IP keying in that case.
        """
        for i in range(2):
            r = self.client.post(
                URL,
                data={'password': 'wrong'},  # no username
                format='json',
                REMOTE_ADDR='10.3.0.1',
            )
            # No username → simplejwt returns 400 (missing required field)
            # OR 401 depending on the simplejwt version. Both are "did not
            # succeed" so they count toward the throttle.
            self.assertIn(r.status_code, (400, 401))
        blocked = self.client.post(
            URL,
            data={'password': 'wrong'},
            format='json',
            REMOTE_ADDR='10.3.0.1',   # same IP → same fallback key
        )
        self.assertEqual(blocked.status_code, 429)


class ConfiguredRatesAreActuallyUsableTests(TestCase):
    """
    M17 regression guard. The live smoke run found that the REAL configured
    rate 'login_account': '10/5min' crashed DRF's parse_rate (KeyError '5')
    — a 500 on every login — because every throttle test above patches
    THROTTLE_RATES and so never exercised the real settings. These tests use
    the real configuration, unpatched.
    """

    def setUp(self):
        cache.clear()

    def test_parse_extended_rate_forms(self):
        from apps.accounts.throttles import parse_extended_rate
        self.assertEqual(parse_extended_rate('10/5min'), (10, 300))
        self.assertEqual(parse_extended_rate('20/min'), (20, 60))
        self.assertEqual(parse_extended_rate('3/s'), (3, 1))
        self.assertEqual(parse_extended_rate('7/2h'), (7, 7200))
        self.assertEqual(parse_extended_rate('100/day'), (100, 86400))
        self.assertEqual(parse_extended_rate(None), (None, None))
        for bad in ('nonsense', '10/', '/min', '10/5years', '10-5min'):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    parse_extended_rate(bad)

    def test_every_configured_default_throttle_rate_is_parseable(self):
        """A rate string that no throttle can parse must fail HERE, at test
        time — never as a per-request 500 in production."""
        from django.conf import settings
        from apps.accounts.throttles import parse_extended_rate
        rates = settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']
        self.assertIn('login_account', rates)
        for scope, rate in rates.items():
            with self.subTest(scope=scope, rate=rate):
                count, duration = parse_extended_rate(rate)
                self.assertGreater(count, 0)
                self.assertGreater(duration, 0)

    def test_login_endpoint_with_real_unpatched_rates_returns_401_not_500(self):
        """The exact failure the smoke test hit: POST /api/v1/auth/token/
        with the real settings. Before the fix this was a 500."""
        client = APIClient()
        resp = client.post(URL, {'username': 'nobody', 'password': 'wrong'},
                           format='json')
        self.assertEqual(resp.status_code, 401)
