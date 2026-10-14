"""
seed_data must be safe to run against a live database in any state:

  * a second full run must not duplicate anything,
  * a partially populated city (exists, but missing a whole category) must be
    completed rather than silently skipped,
  * records that already exist - including ones added by hand - must be
    preserved untouched, never deleted or duplicated.

No network is touched: without UNSPLASH_ACCESS_KEY image URLs are plain
strings.
"""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.adventures.models import Adventure
from apps.hotels.models import Hotel
from apps.locations.models import City
from apps.vehicles.models import Vehicle


def _counts():
    return (City.objects.count(), Hotel.objects.count(),
            Adventure.objects.count(), Vehicle.objects.count())


def _seed():
    out = StringIO()
    call_command('seed_data', stdout=out)
    return out.getvalue()


class SeedDataIdempotencyTests(TestCase):
    def test_second_run_does_not_duplicate_catalog(self):
        _seed()
        first = _counts()
        self.assertEqual(first, (12, 36, 36, 36))
        _seed()
        self.assertEqual(_counts(), first)

    def test_partially_populated_city_gets_missing_category_refilled(self):
        """A city with zero hotels must get hotels on rerun, not be skipped."""
        _seed()
        city = City.objects.get(name='Goa')
        # Simulate partial population (test database only - production data
        # is never deleted by the command or the workflow).
        Hotel.objects.filter(city=city).delete()
        self.assertEqual(Hotel.objects.count(), 33)

        output = _seed()
        self.assertEqual(Hotel.objects.filter(city=city).count(), 3)
        self.assertEqual(_counts(), (12, 36, 36, 36))
        # The skip of still-populated categories is reported, not silent.
        self.assertIn('already present - skipped', output)

    def test_existing_extra_records_are_preserved_not_duplicated(self):
        """Hand-added records survive a rerun and are not topped up around."""
        _seed()
        city = City.objects.get(name='Manali')
        extra = Hotel.objects.create(
            city=city,
            name='Operator Added Hotel',
            description='added manually, must survive reruns',
            price_per_night=Decimal('999.00'),
            total_rooms=5,
            available_rooms=5,
            latitude=city.latitude,
            longitude=city.longitude,
            amenities=['WiFi'],
            rating=Decimal('4.0'),
            image_url='https://example.com/x.jpg',
            is_active=True,
        )

        _seed()
        extra.refresh_from_db()  # raises if it had been deleted
        self.assertEqual(extra.name, 'Operator Added Hotel')
        # Manali keeps its 3 seeded + 1 manual hotel; nothing else changed.
        self.assertEqual(Hotel.objects.filter(city=city).count(), 4)
        self.assertEqual(_counts(), (12, 37, 36, 36))
