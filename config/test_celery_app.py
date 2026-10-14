"""
Tests for the Celery application wiring (checklist G01).

These tests never contact a broker. They check that the app object exists,
is exported from the `config` package, is configured safely, and that a task
can be registered and executed locally with .apply() (which runs in-process,
without Redis).

They do NOT prove a real worker can reach a real broker. That needs a
manual run of the worker against Redis (see the smoke-test steps).
"""
from django.test import SimpleTestCase

import config
from config.celery import app, debug_task


class CeleryAppWiringTests(SimpleTestCase):
    def test_celery_app_is_exported_from_config_package(self):
        self.assertIs(config.celery_app, app)

    def test_app_has_expected_name(self):
        self.assertEqual(app.main, "travelx")

    def test_broker_url_is_configured(self):
        broker_url = app.conf.broker_url
        self.assertTrue(broker_url)
        self.assertTrue(
            broker_url.startswith(("redis://", "rediss://", "amqp://", "amqps://")),
            f"Unexpected broker scheme: {broker_url!r}",
        )

    def test_only_json_serialization_is_accepted(self):
        self.assertEqual(app.conf.task_serializer, "json")
        self.assertEqual(list(app.conf.accept_content), ["json"])
        self.assertEqual(app.conf.result_serializer, "json")

    def test_broker_connection_retry_on_startup_enabled(self):
        self.assertTrue(app.conf.broker_connection_retry_on_startup)


class CeleryTaskRegistrationTests(SimpleTestCase):
    def test_debug_task_is_registered_with_the_app(self):
        self.assertIn("config.celery.debug_task", app.tasks)

    def test_debug_task_runs_locally_without_a_broker(self):
        result = debug_task.apply()
        self.assertTrue(result.successful())
        self.assertEqual(result.get(), "celery-ok")