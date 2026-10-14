import json
import sys

from django.core.management.base import BaseCommand

from apps.core.monitoring import STATUS_DEGRADED, STATUS_DOWN, collect


class Command(BaseCommand):
    help = (
        "Print the dependency status report. Exit code 2 if status is down; "
        "with --strict, exit code 1 if degraded."
    )

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Print raw JSON.")
        parser.add_argument(
            "--strict", action="store_true", help="Exit 1 when status is degraded."
        )

    def handle(self, *args, **options):
        report = collect()
        if options["json"]:
            self.stdout.write(json.dumps(report, indent=2))
        else:
            self.stdout.write(f"overall: {report['status']}  ({report['checked_at']})")
            for name, entry in report["checks"].items():
                line = f"  {name:<15} {entry['state']:<5} {entry['latency_ms']:>8} ms"
                if entry.get("reason"):
                    line += f"  - {entry['reason']}"
                self.stdout.write(line)

        status = report["status"]
        if status == STATUS_DOWN:
            sys.exit(2)
        if status == STATUS_DEGRADED and options["strict"]:
            sys.exit(1)