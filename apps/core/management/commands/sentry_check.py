from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send one test exception to Sentry to verify the DSN and alert routing."

    def handle(self, *args, **options):
        if not getattr(settings, "SENTRY_DSN", ""):
            raise CommandError("SENTRY_DSN is not set; error tracking is disabled.")
        import sentry_sdk

        try:
            raise RuntimeError("TravelX Sentry test event (safe to ignore)")
        except RuntimeError as exc:
            event_id = sentry_sdk.capture_exception(exc)
        sentry_sdk.flush(timeout=5)
        self.stdout.write(self.style.SUCCESS(f"Test event sent: {event_id}"))