from unittest import mock

from django.db.utils import OperationalError
from django.test import TestCase, override_settings


class LivenessTests(TestCase):
    def test_live_returns_ok_without_touching_the_database(self):
        with self.assertNumQueries(0):
            response = self.client.get("/health/live/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_live_accepts_head(self):
        self.assertEqual(self.client.head("/health/live/").status_code, 200)

    def test_live_rejects_post(self):
        self.assertEqual(self.client.post("/health/live/").status_code, 405)

    def test_live_is_not_cached(self):
        response = self.client.get("/health/live/")
        self.assertIn("no-cache", response["Cache-Control"])

    def test_live_carries_the_h01_request_id(self):
        response = self.client.get("/health/live/", HTTP_X_REQUEST_ID="probe-req-12345")
        self.assertEqual(response["X-Request-ID"], "probe-req-12345")


class ReadinessTests(TestCase):
    def test_ready_ok_with_default_checks(self):
        response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["checks"], {"database": "ok", "cache": "ok"})

    def test_ready_rejects_post(self):
        self.assertEqual(self.client.post("/health/ready/").status_code, 405)

    def test_ready_is_not_cached(self):
        self.assertIn("no-cache", self.client.get("/health/ready/")["Cache-Control"])

    def test_database_failure_gives_503_and_leaks_nothing(self):
        with mock.patch("apps.core.health.connection") as fake_connection:
            fake_connection.cursor.side_effect = OperationalError(
                "could not connect to host db.internal password=hunter2"
            )
            response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["status"], "unavailable")
        self.assertEqual(body["checks"]["database"], "fail")
        self.assertEqual(body["checks"]["cache"], "ok")
        raw = response.content.decode()
        self.assertNotIn("hunter2", raw)
        self.assertNotIn("db.internal", raw)

    def test_cache_failure_gives_503(self):
        with mock.patch("apps.core.health.cache") as fake_cache:
            fake_cache.set.side_effect = ConnectionError("redis down")
            response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["checks"]["cache"], "fail")
        self.assertEqual(response.json()["checks"]["database"], "ok")

    def test_cache_roundtrip_mismatch_is_a_failure(self):
        with mock.patch("apps.core.health.cache") as fake_cache:
            fake_cache.get.return_value = None
            response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)

    @override_settings(HEALTH_READINESS_CHECKS=["database", "bogus"])
    def test_unknown_check_name_is_reported_as_failure(self):
        response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["checks"]["bogus"], "fail")

    @override_settings(HEALTH_READINESS_CHECKS=["broker"])
    def test_broker_check_ok(self):
        with mock.patch("kombu.Connection") as fake_conn:
            response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 200)
        fake_conn.return_value.ensure_connection.assert_called_once()
        fake_conn.return_value.release.assert_called_once()

    @override_settings(HEALTH_READINESS_CHECKS=["broker"])
    def test_broker_failure_gives_503_and_releases_connection(self):
        with mock.patch("kombu.Connection") as fake_conn:
            fake_conn.return_value.ensure_connection.side_effect = OSError("refused")
            response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["checks"]["broker"], "fail")
        fake_conn.return_value.release.assert_called_once()

    @override_settings(HEALTH_READINESS_CHECKS=["kafka"])
    def test_kafka_check_ok(self):
        with mock.patch("confluent_kafka.admin.AdminClient") as fake_admin:
            response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 200)
        fake_admin.return_value.list_topics.assert_called_once()

    @override_settings(HEALTH_READINESS_CHECKS=["kafka"])
    def test_kafka_failure_gives_503(self):
        with mock.patch("confluent_kafka.admin.AdminClient") as fake_admin:
            fake_admin.return_value.list_topics.side_effect = RuntimeError("timeout")
            response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["checks"]["kafka"], "fail")