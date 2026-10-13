"""G08: outbox relay. Moves OutboxEvent rows to Kafka.

Loops forever by default (the outbox_relay container). --once does a single
pass and exits (tests, manual checks).
"""
import logging
import time

from django.core.management.base import BaseCommand

from apps.kafka_events.outbox import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_ATTEMPTS,
    publish_pending_events,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Publish pending outbox events to Kafka (loops until stopped; --once for one pass)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run a single pass and exit.")
        parser.add_argument("--interval", type=float, default=1.0, help="Seconds between passes.")
        parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
        parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)

    def handle(self, *args, **options):
        once = options["once"]
        interval = max(options["interval"], 0.1)
        self.stdout.write("Outbox relay started")
        try:
            while True:
                try:
                    result = publish_pending_events(
                        batch_size=options["batch_size"],
                        max_attempts=options["max_attempts"],
                    )
                except Exception:
                    if once:
                        raise
                    logger.exception("outbox relay pass failed; will retry")
                else:
                    if once or any(result.values()):
                        summary = " ".join(f"{key}={value}" for key, value in result.items())
                        self.stdout.write(f"Outbox relay pass finished: {summary}")
                if once:
                    return
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("Outbox relay stopped")