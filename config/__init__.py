# Make sure the Celery app is loaded whenever Django starts, so that
# @shared_task decorators in any app bind to it.
from .celery import app as celery_app

__all__ = ("celery_app",)