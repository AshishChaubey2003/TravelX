"""G10: operator recovery tooling.

  manage.py recovery status
  manage.py recovery replay-outbox  (--all | --ids 1 2 3)
  manage.py recovery replay-events  (--all | --ids ...)
  manage.py recovery replay-tasks   (--all | --ids ...)

Replays never run without an explicit selection.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from apps.kafka_events import recovery

_REPLAY_FUNCTIONS = {
    "replay-outbox": "replay_dead_outbox",
    "replay-events": "replay_dead_events",
    "replay-tasks": "replay_failed_tasks",
}


class Command(BaseCommand):
    help = "Inspect and replay dead-lettered outbox rows, failed events and failed tasks."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", *_REPLAY_FUNCTIONS])
        parser.add_argument("--all", action="store_true", help="Replay every eligible row.")
        parser.add_argument("--ids", type=int, nargs="+", help="Replay only these row ids.")

    def handle(self, *args, **options):
        action = options["action"]
        if action == "status":
            summary = recovery.status_summary()
            self.stdout.write(json.dumps(summary, indent=2, sort_keys=True, default=str))
            if not any(summary.get(key) for key in ("outbox", "failed_events", "failed_tasks")):
                self.stdout.write("Nothing to recover: all queues are empty.")
            return

        select_all, ids = options["all"], options["ids"]
        if select_all and ids:
            raise CommandError("Use either --all or --ids, not both.")
        if not select_all and not ids:
            raise CommandError("Refusing to replay without a selection: pass --all or --ids.")

        function = getattr(recovery, _REPLAY_FUNCTIONS[action])
        result = function(ids=None if select_all else ids)
        self.stdout.write(f"{action}: {result}")