"""Static checks for Dockerfile / .dockerignore / docker-compose.yml (H07).

They read the files only; they do NOT build images or start containers.
Real container behaviour is checked by the manual Phase 2 steps.
"""
import importlib.util
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
HAS_YAML = importlib.util.find_spec("yaml") is not None

APP_SERVICES = ["web", "celery_worker", "celery_beat", "kafka_consumer", "outbox_relay", "migrate"]


def _text(name):
    return (ROOT / name).read_text(encoding="utf-8")


def _command(service):
    command = service.get("command", "")
    return " ".join(command) if isinstance(command, list) else str(command)


class DockerfileTests(SimpleTestCase):
    def setUp(self):
        self.lines = [
            line.strip() for line in _text("Dockerfile").splitlines() if line.strip()
        ]

    def test_has_exactly_one_build_stage(self):
        self.assertEqual(len([l for l in self.lines if l.startswith("FROM ")]), 1)

    def test_python_version_matches_ci(self):
        self.assertTrue(self.lines[0].startswith("FROM python:3.12"))

    def test_dependencies_are_installed_before_source_is_copied(self):
        text = _text("Dockerfile")
        self.assertLess(text.index("COPY requirements.txt"), text.index("COPY . ."))

    def test_default_command_runs_gunicorn_on_the_wsgi_app(self):
        cmd = [l for l in self.lines if l.startswith("CMD ")][0]
        self.assertIn("gunicorn config.wsgi:application", cmd)


class DockerignoreTests(SimpleTestCase):
    def test_env_files_and_git_are_excluded_from_the_image(self):
        entries = {l.strip() for l in _text(".dockerignore").splitlines()}
        self.assertIn(".env", entries)
        self.assertIn(".git", entries)

    def test_env_example_is_still_allowed(self):
        self.assertIn("!.env.example", _text(".dockerignore"))


@skipUnless(HAS_YAML, "PyYAML not installed")
class ComposeTests(SimpleTestCase):
    def setUp(self):
        import yaml

        self.compose = yaml.safe_load(_text("docker-compose.yml"))
        self.services = self.compose["services"]

    def test_obsolete_version_key_is_gone(self):
        self.assertNotIn("version", self.compose)

    def test_all_expected_services_exist(self):
        expected = {
            "db", "redis", "zookeeper", "kafka", "migrate", "web",
            "celery_worker", "celery_beat", "kafka_consumer", "outbox_relay",
        }
        self.assertTrue(expected <= set(self.services))

    def test_app_services_share_one_image_built_from_the_dockerfile(self):
        images = {self.services[n]["image"] for n in APP_SERVICES}
        self.assertEqual(len(images), 1)
        for name in APP_SERVICES:
            build = self.services[name]["build"]
            self.assertEqual(build["dockerfile"], "Dockerfile")

    def test_app_services_load_env_from_env_file_not_inline_secrets(self):
        for name in APP_SERVICES:
            self.assertIn(".env", self.services[name]["env_file"])

    def test_commands_target_the_right_programs(self):
        self.assertIn("celery -A config worker", _command(self.services["celery_worker"]))
        beat = _command(self.services["celery_beat"])
        self.assertIn("celery -A config beat", beat)
        self.assertIn("django_celery_beat.schedulers:DatabaseScheduler", beat)
        self.assertIn("run_consumer", _command(self.services["kafka_consumer"]))
        self.assertIn("publish_outbox", _command(self.services["outbox_relay"]))
        self.assertIn("manage.py migrate", _command(self.services["migrate"]))

    def test_referenced_management_commands_exist(self):
        base = ROOT / "apps" / "kafka_events" / "management" / "commands"
        self.assertTrue((base / "run_consumer.py").exists())
        self.assertTrue((base / "publish_outbox.py").exists())

    def test_celery_app_is_exported_for_dash_a_config(self):
        self.assertIn("celery_app", _text("config/__init__.py"))
        self.assertIn("Celery(", _text("config/celery.py"))

    def test_migrations_run_once_in_a_dedicated_service(self):
        self.assertNotIn("migrate", _command(self.services["web"]).replace("PROMETHEUS", ""))
        for name in ["web", "celery_worker", "celery_beat", "kafka_consumer", "outbox_relay"]:
            condition = self.services[name]["depends_on"]["migrate"]["condition"]
            self.assertEqual(condition, "service_completed_successfully")

    def test_kafka_users_wait_for_a_healthy_kafka(self):
        self.assertIn("healthcheck", self.services["kafka"])
        for name in ["kafka_consumer", "outbox_relay"]:
            self.assertEqual(
                self.services[name]["depends_on"]["kafka"]["condition"], "service_healthy"
            )

    def test_infrastructure_and_app_healthchecks_exist(self):
        for name in ["db", "redis", "kafka", "web", "celery_worker"]:
            self.assertIn("healthcheck", self.services[name], name)

    def test_web_healthcheck_uses_the_h02_liveness_endpoint(self):
        test = " ".join(self.services["web"]["healthcheck"]["test"])
        self.assertIn("/health/live/", test)

    def test_web_sets_a_shared_metrics_directory_for_gunicorn_workers(self):
        directory = self.services["web"]["environment"]["PROMETHEUS_MULTIPROC_DIR"]
        self.assertTrue(directory.startswith("/"))
        self.assertIn("PROMETHEUS_MULTIPROC_DIR", _command(self.services["web"]))

    def test_every_service_that_needs_the_database_waits_for_it_healthy(self):
        for name in APP_SERVICES:
            self.assertEqual(
                self.services[name]["depends_on"]["db"]["condition"], "service_healthy"
            )

    def test_long_running_services_restart_but_migrate_does_not(self):
        self.assertEqual(self.services["migrate"]["restart"], "no")
        for name in ["web", "celery_worker", "celery_beat", "kafka_consumer", "outbox_relay"]:
            self.assertEqual(self.services[name]["restart"], "unless-stopped")