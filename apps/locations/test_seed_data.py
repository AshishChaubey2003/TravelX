"""
Running seed_data twice must not duplicate the catalog (cities used
get_or_create, but hotels/adventures/vehicles used plain create()). No network
is touched: without UNSPLASH_ACCESS_KEY image URLs are plain strings.
"""
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


class SeedDataIdempotencyTests(TestCase):
    def test_second_run_does_not_duplicate_catalog(self):
        call_command('seed_data', stdout=StringIO())
        first = _counts()
        self.assertEqual(first, (12, 36, 36, 36))
        call_command('seed_data', stdout=StringIO())
        self.assertEqual(_counts(), first)
