"""
Read-only database diagnostic for TravelX.

Prints, for the database Django is currently configured to use:
  - engine, host, and database name (NEVER credentials),
  - whether any migrations are unapplied (and which),
  - row counts for the catalog (cities, hotels, adventures, vehicles),
  - user totals (total / active / inactive).

It executes SELECT/metadata queries only — it cannot modify anything.

Intended use: run locally with DATABASE_URL set for this one process to the
production connection string (your local dev setup stays on SQLite — the env
var only affects this invocation). The --expect-host gate refuses to run
against any host that does not contain the given substring, so a wrong or
leftover DATABASE_URL is caught before any result is trusted.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = (
        "Read-only report: db target (no credentials), unapplied migrations, "
        "catalog and user counts. Use --expect-host to pin the intended target."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--expect-host",
            required=True,
            help=(
                "Substring the connected database HOST must contain "
                "(e.g. 'neon.tech'). Refuses any other target."
            ),
        )

    def handle(self, *args, **opts):
        d = connection.settings_dict
        engine, host, name = d["ENGINE"], d["HOST"], d["NAME"]
        self.stdout.write(f"engine: {engine}")
        self.stdout.write(f"host:   {host}")
        self.stdout.write(f"db:     {name}")

        expect = (opts["expect_host"] or "").strip()
        if not expect:
            # An empty substring is contained in every host, which would
            # defeat the gate entirely - refuse it outright.
            raise CommandError("REFUSED: --expect-host must not be empty.")
        if expect not in (host or ""):
            raise CommandError(
                "REFUSED: connected host does not contain "
                f"--expect-host {expect!r} - wrong database target."
            )

        # Migration status (read-only plan computation).
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            self.stdout.write(self.style.WARNING(f"unapplied migrations: {len(plan)}"))
            for migration, _backwards in plan:
                self.stdout.write(f"  - {migration.app_label}.{migration.name}")
        else:
            self.stdout.write(self.style.SUCCESS("migrations: all applied"))

        # Catalog counts (read-only).
        from apps.adventures.models import Adventure
        from apps.hotels.models import Hotel
        from apps.locations.models import City
        from apps.vehicles.models import Vehicle

        try:
            self.stdout.write(
                "catalog: cities=%d hotels=%d adventures=%d vehicles=%d"
                % (
                    City.objects.count(),
                    Hotel.objects.count(),
                    Adventure.objects.count(),
                    Vehicle.objects.count(),
                )
            )
            total = User.objects.count()
            active = User.objects.filter(is_active=True).count()
            self.stdout.write(
                f"users: total={total} active={active} inactive={total - active}"
            )
        except Exception as exc:
            # e.g. tables missing because migrations are unapplied.
            self.stdout.write(
                self.style.WARNING(
                    f"counts unavailable ({type(exc).__name__}) - apply migrations first"
                )
            )
