"""
The city list must report the same hotel/adventure counts it always did,
while issuing a constant number of queries instead of one COUNT per city
per field (12 cities previously cost 26 queries; every one of them is a
round-trip to the remote production database).

These tests pin both halves: the counts stay correct (including the
is_active filtering and the two-relation join that needs distinct=True),
and the query count does not grow with the number of cities.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.adventures.models import Adventure
from apps.hotels.models import Hotel
from apps.locations.models import City
from apps.locations.serializers import CitySerializer


def _city(name, state='Test State'):
    return City.objects.create(
        name=name, state=state,
        latitude=Decimal('10.000000'), longitude=Decimal('20.000000'),
        is_active=True,
    )


def _hotel(city, is_active=True, name='H'):
    return Hotel.objects.create(
        city=city, name=name, description='d',
        price_per_night=Decimal('1000.00'), total_rooms=10, available_rooms=5,
        latitude=city.latitude, longitude=city.longitude,
        amenities=['WiFi'], rating=Decimal('4.0'), is_active=is_active,
    )


def _adventure(city, is_active=True, name='A'):
    return Adventure.objects.create(
        city=city, name=name, description='d',
        price_per_person=Decimal('500.00'), max_capacity=10, current_bookings=0,
        duration_hours=2, difficulty='EASY',
        latitude=city.latitude, longitude=city.longitude, is_active=is_active,
    )


class CityListCountAccuracyTests(TestCase):
    def test_counts_exclude_inactive_and_are_not_multiplied(self):
        city = _city('Countsville')
        # 2 active + 1 inactive hotels, 3 active + 1 inactive adventures.
        # Both relations are counted in one query, so without distinct=True
        # the join would multiply these numbers together.
        for i in range(2):
            _hotel(city, True, f'active-hotel-{i}')
        _hotel(city, False, 'inactive-hotel')
        for i in range(3):
            _adventure(city, True, f'active-adv-{i}')
        _adventure(city, False, 'inactive-adv')

        resp = self.client.get(reverse('city-list'))
        self.assertEqual(resp.status_code, 200)
        row = next(r for r in resp.json()['results'] if r['name'] == 'Countsville')
        self.assertEqual(row['hotel_count'], 2)
        self.assertEqual(row['adventure_count'], 3)

    def test_city_with_no_children_reports_zero(self):
        _city('Emptyville')
        resp = self.client.get(reverse('city-list'))
        row = next(r for r in resp.json()['results'] if r['name'] == 'Emptyville')
        self.assertEqual(row['hotel_count'], 0)
        self.assertEqual(row['adventure_count'], 0)

    def test_cities_stay_alphabetical(self):
        """Annotating adds a GROUP BY, which drops City.Meta.ordering.

        The view compensates with an explicit order_by('name'); without it
        the list comes back in an arbitrary order and pagination is unstable.
        """
        for name in ['Zanzibar', 'Alpha City', 'Mumbai', 'Bengaluru']:
            _city(name)
        results = self.client.get(reverse('city-list')).json()['results']
        names = [r['name'] for r in results]
        self.assertEqual(names, sorted(names))
        self.assertEqual(names[0], 'Alpha City')

    def test_search_filter_still_applies(self):
        _city('Searchable Town')
        _city('Other Place')
        results = self.client.get(reverse('city-list'), {'search': 'searchable'}).json()
        self.assertEqual(results['count'], 1)
        self.assertEqual(results['results'][0]['name'], 'Searchable Town')

    def test_serializer_still_correct_without_the_annotation(self):
        """A plain instance (no annotation) must fall back, not crash."""
        city = _city('Fallbackville')
        _hotel(city, True)
        _adventure(city, False)
        data = CitySerializer(City.objects.get(pk=city.pk)).data
        self.assertEqual(data['hotel_count'], 1)
        self.assertEqual(data['adventure_count'], 0)


class CityListQueryBudgetTests(TestCase):
    def test_query_count_does_not_grow_with_city_count(self):
        for i in range(3):
            c = _city(f'Small {i}')
            _hotel(c)
            _adventure(c)
        with self.assertNumQueries(2):  # 1 COUNT for pagination + 1 page query
            self.client.get(reverse('city-list'))

        for i in range(9):
            c = _city(f'Large {i}')
            _hotel(c)
            _adventure(c)
        self.assertEqual(City.objects.count(), 12)
        with self.assertNumQueries(2):  # still 2 with 4x the cities
            resp = self.client.get(reverse('city-list'))
        self.assertEqual(resp.json()['count'], 12)
