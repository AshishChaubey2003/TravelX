"""
Celery application for TravelX (checklist G01).

All broker/result-backend/timezone/beat-scheduler values come from the
CELERY_* settings already defined in config/settings.py (namespace="CELERY"),
so there is a single source of truth.

Run the worker:  celery -A config worker -l info
Run the beat:    celery -A config beat -l info
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("travelx")

# Reads CELERY_BROKER_URL, CELERY_RESULT_BACKEND, CELERY_ACCEPT_CONTENT,
# CELERY_TASK_SERIALIZER, CELERY_TIMEZONE, CELERY_BEAT_SCHEDULER from settings.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Celery 5.x: keep retrying the broker connection at worker startup instead
# of failing immediately if Redis is still booting.
app.conf.broker_connection_retry_on_startup = True

# Finds a `tasks.py` inside every app listed in INSTALLED_APPS.
app.autodiscover_tasks()

from apps.core.logging_utils import connect_celery_signals  # noqa: E402

connect_celery_signals()

@app.task(name="config.celery.debug_task")
def debug_task():
    """Tiny smoke-test task proving the app and worker are wired up."""
    return "celery-ok"