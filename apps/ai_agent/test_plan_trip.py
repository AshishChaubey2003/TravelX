from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle


class PlanTripValidationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = '/api/v1/ai/plan/'
        cache.clear()

    def test_missing_query_returns_400(self):
        resp = self.client.post(self.url, {}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_blank_query_returns_400(self):
        resp = self.client.post(self.url, {'query': '   '}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_non_string_query_returns_400(self):
        resp = self.client.post(self.url, {'query': {'a': 1}}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_too_long_query_returns_400(self):
        resp = self.client.post(self.url, {'query': 'x' * 501}, format='json')
        self.assertEqual(resp.status_code, 400)

    @patch('apps.ai_agent.views.get_cities', return_value=[])
    def test_valid_query_follows_planner_flow(self, mock_cities):
        resp = self.client.post(self.url, {'query': 'Goa'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('response', resp.data)

    @patch('apps.ai_agent.views.get_cities', side_effect=RuntimeError('boom'))
    def test_unexpected_exception_returns_safe_500(self, mock_cities):
        with self.assertLogs('travelx.request', level='ERROR') as log_ctx:
            resp = self.client.post(self.url, {'query': 'Goa'}, format='json')
        self.assertEqual(resp.status_code, 500)
        self.assertNotIn('boom', str(resp.data))
        self.assertTrue(any('PlanTripView' in msg for msg in log_ctx.output))


class PlanTripThrottleTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = '/api/v1/ai/plan/'
        cache.clear()

    # FIX (F-22 throttle test follow-up): ScopedRateThrottle.THROTTLE_RATES is
    # a class attribute bound once at import time from api_settings; it is
    # read live on every request but NOT refreshed by override_settings().
    # patch.dict mutates that same shared dict in place for this test only,
    # and restores the original (production) rate automatically afterward.
    @patch.dict(ScopedRateThrottle.THROTTLE_RATES, {'ai_plan_trip': '2/min'})
    @patch('apps.ai_agent.views.get_cities', return_value=[])
    def test_anonymous_throttle_returns_429_after_limit(self, mock_cities):
        r1 = self.client.post(self.url, {'query': 'Goa'}, format='json')
        r2 = self.client.post(self.url, {'query': 'Goa'}, format='json')
        r3 = self.client.post(self.url, {'query': 'Goa'}, format='json')
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r3.status_code, 429)