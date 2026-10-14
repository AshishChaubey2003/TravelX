"""
Safety-gate tests for the read-only diagnose_db management command.

The command refuses to run unless the connected database's HOST contains the
required --expect-host substring, so a wrong or leftover DATABASE_URL (or a
local SQLite database, whose HOST is empty) can never be mistaken for the
production target. The positive path is exercised for real by the manual
"Production DB" GitHub Actions workflow against the production host.
"""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


class DiagnoseDbGateTests(TestCase):
    def test_refuses_when_host_does_not_match(self):
        # The test database is SQLite (HOST is empty); a gate pinned to the
        # production host must refuse it.
        with self.assertRaises(CommandError) as ctx:
            call_command('diagnose_db', '--expect-host', 'neon.tech',
                         stdout=StringIO())
        self.assertIn('REFUSED', str(ctx.exception))

    def test_refuses_empty_expect_host(self):
        # '' is a substring of every host, which would defeat the gate.
        with self.assertRaises(CommandError) as ctx:
            call_command('diagnose_db', '--expect-host', '',
                         stdout=StringIO())
        self.assertIn('REFUSED', str(ctx.exception))

    def test_expect_host_is_required(self):
        with self.assertRaises(CommandError):
            call_command('diagnose_db', stdout=StringIO())
