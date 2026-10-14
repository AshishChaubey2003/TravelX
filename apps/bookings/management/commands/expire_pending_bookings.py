"""
F-005 — manual invocation of the (dormant) expiry sweep.

    python manage.py expire_pending_bookings            # default cutoff
    python manage.py expire_pending_bookings --minutes 60
    python manage.py expire_pending_bookings --dry-run  # list, change nothing

This is the ONLY sanctioned way to run the sweep until a beat schedule is
separately approved. The sweep itself re-checks every condition under the
booking row lock (see apps/bookings/tasks_expiry.py).
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Expire stale PENDING bookings with no Payment row (F-005; dormant sweep)."

    def add_arguments(self, parser):
        parser.add_argument('--minutes', type=int, default=None,
                            help='Override BOOKING_PENDING_EXPIRY_MINUTES for this run.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Only list candidate bookings; change nothing.')

    def handle(self, *args, **options):
        from apps.bookings.models import Booking
        from apps.bookings.tasks_expiry import _cutoff, expire_stale_pending_bookings

        cutoff = _cutoff(options['minutes'])

        if options['dry_run']:
            candidates = Booking.objects.filter(
                status='PENDING', created_at__lt=cutoff, payment__isnull=True,
            ).order_by('created_at')
            self.stdout.write(f'Cutoff: {cutoff.isoformat()} (now {timezone.now().isoformat()})')
            self.stdout.write(f'{candidates.count()} candidate booking(s); nothing changed:')
            for b in candidates[:50]:
                self.stdout.write(f'  {b.pk}  created {b.created_at.isoformat()}')
            return

        # Synchronous call — no broker involved; the locked rechecks inside
        # the sweep are what make this safe to run at any time.
        summary = expire_stale_pending_bookings(minutes=options['minutes'])
        self.stdout.write(self.style.SUCCESS(f'Expiry sweep: {summary}'))
