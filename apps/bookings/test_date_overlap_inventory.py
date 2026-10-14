"""
F-004 Phase 1 — date-aware inventory gate (dual gate: overlap count + legacy
counters, both retained).

HONESTY NOTE (SQLite vs PostgreSQL): every test in the TestCase classes below
runs on SQLite and validates the ARITHMETIC of the overlap gate only. SQLite
ignores SELECT ... FOR UPDATE, so nothing here proves row-lock concurrency.
The concurrency tests live in PostgresConcurrencyTests, which SKIP unless the
test database is PostgreSQL and must be reported as BLOCKED until run there.

Fixture trick used throughout: holds are created DIRECTLY as Booking +
BookingItem rows (bypassing the service), which leaves the legacy counters
untouched. That isolates the new overlap gate: when a test asserts the
"... for the selected dates." message, the legacy gate provably did not fire.
"""
import threading

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from unittest import skipUnless

from apps.bookings.models import Booking, BookingItem
from apps.bookings.services import BookingService
from apps.bookings.test_services import (
    _make_adventure,
    _make_city,
    _make_hotel,
    _make_user,
    _make_vehicle,
)

NEW_GATE_HOTEL = "No rooms available for the selected dates."
LEGACY_GATE_HOTEL = "No rooms available!"
NEW_GATE_ADVENTURE = "Not enough spots available for the selected dates."
NEW_GATE_VEHICLE = "Vehicle not available for the selected dates."


def _hold(user, item_type, obj, check_in, check_out, status="PENDING", quantity=1):
    """A date hold written directly to the tables — legacy counters untouched."""
    booking = Booking.objects.create(
        user=user,
        status=status,
        total_amount=1000,
        check_in=check_in,
        check_out=check_out,
    )
    BookingItem.objects.create(
        booking=booking,
        item_type=item_type,
        item_id=obj.id,
        item_name=obj.name,
        price_at_booking=1000,
        quantity=quantity,
        nights=None,
    )
    return booking


class OverlapCountArithmeticTests(TestCase):
    """_overlap_count in isolation (SQLite: arithmetic only, no concurrency)."""

    def setUp(self):
        self.city = _make_city()
        self.user = _make_user("overlap_arith")
        self.hotel = _make_hotel(self.city)

    def test_half_open_boundaries_same_day_turnover_is_not_an_overlap(self):
        _hold(self.user, "HOTEL", self.hotel, "2026-11-01", "2026-11-03")
        from datetime import date
        self.assertEqual(
            BookingService._overlap_count(
                "HOTEL", self.hotel.id, date(2026, 11, 3), date(2026, 11, 5)),
            0,  # [1,3) and [3,5) do not overlap: A.check_out > B.check_in fails
        )
        self.assertEqual(
            BookingService._overlap_count(
                "HOTEL", self.hotel.id, date(2026, 11, 2), date(2026, 11, 4)),
            1,
        )

    def test_quantities_are_summed_not_counted(self):
        _hold(self.user, "HOTEL", self.hotel, "2026-11-01", "2026-11-05", quantity=3)
        from datetime import date
        self.assertEqual(
            BookingService._overlap_count(
                "HOTEL", self.hotel.id, date(2026, 11, 2), date(2026, 11, 3)),
            3,
        )


class HotelOverlapGateTests(TestCase):
    def setUp(self):
        self.city = _make_city()
        self.user = _make_user("overlap_hotel")

    def _book(self, hotel, check_in, check_out):
        return BookingService.create_booking(self.user, {
            "hotel_id": str(hotel.id),
            "check_in": check_in,
            "check_out": check_out,
        })

    def test_partial_overlap_counts_against_capacity(self):
        hotel = _make_hotel(self.city, total_rooms=2, available_rooms=2)
        _hold(self.user, "HOTEL", hotel, "2026-11-01", "2026-11-05")
        _hold(self.user, "HOTEL", hotel, "2026-11-01", "2026-11-05")
        with self.assertRaisesMessage(ValueError, NEW_GATE_HOTEL):
            self._book(hotel, "2026-11-04", "2026-11-06")  # overlaps Nov 4
        # Legacy counter (2 rooms free) provably did not fire: the message is
        # the new gate's.

    def test_pending_booking_counts_against_overlap(self):
        hotel = _make_hotel(self.city, total_rooms=1, available_rooms=1)
        _hold(self.user, "HOTEL", hotel, "2026-11-01", "2026-11-03", status="PENDING")
        with self.assertRaisesMessage(ValueError, NEW_GATE_HOTEL):
            self._book(hotel, "2026-11-02", "2026-11-04")

    def test_confirmed_and_paid_bookings_count_against_overlap(self):
        hotel = _make_hotel(self.city, total_rooms=2, available_rooms=2)
        _hold(self.user, "HOTEL", hotel, "2026-11-01", "2026-11-03", status="CONFIRMED")
        _hold(self.user, "HOTEL", hotel, "2026-11-01", "2026-11-03", status="PAID")
        with self.assertRaisesMessage(ValueError, NEW_GATE_HOTEL):
            self._book(hotel, "2026-11-02", "2026-11-04")

    def test_cancelled_bookings_do_not_count_toward_overlap(self):
        hotel = _make_hotel(self.city, total_rooms=1, available_rooms=1)
        _hold(self.user, "HOTEL", hotel, "2026-11-01", "2026-11-03", status="CANCELLED")
        booking = self._book(hotel, "2026-11-02", "2026-11-04")
        self.assertEqual(booking.status, "PENDING")

    def test_same_day_turnover_passes_overlap_gate_but_legacy_gate_still_rejects(self):
        """Phase 1 pins the KNOWN false negative: the date-blind legacy
        counter rejects a second, non-overlapping booking. This test asserts
        the LEGACY message, proving the overlap gate passed. It is replaced in
        Phase 2 by test_two_non_overlapping_bookings_both_succeed."""
        hotel = _make_hotel(self.city, total_rooms=1, available_rooms=1)
        self._book(hotel, "2026-11-01", "2026-11-03")  # consumes the counter
        with self.assertRaisesMessage(ValueError, LEGACY_GATE_HOTEL):
            self._book(hotel, "2026-11-03", "2026-11-05")  # no date overlap

    def test_resource_isolation_other_hotel_same_dates_books_fine(self):
        hotel_a = _make_hotel(self.city, name="Hotel A", total_rooms=1, available_rooms=1)
        hotel_b = _make_hotel(self.city, name="Hotel B", total_rooms=1, available_rooms=1)
        _hold(self.user, "HOTEL", hotel_a, "2026-11-01", "2026-11-03")
        booking = self._book(hotel_b, "2026-11-01", "2026-11-03")
        self.assertEqual(booking.items.get().item_id, hotel_b.id)


class AdventureAndVehicleOverlapGateTests(TestCase):
    def setUp(self):
        self.city = _make_city()
        self.user = _make_user("overlap_av")

    def test_adventure_spot_overlap_rejects_overbook(self):
        adventure = _make_adventure(self.city, max_capacity=10, current_bookings=0)
        _hold(self.user, "ADVENTURE", adventure, "2026-11-01", "2026-11-03", quantity=6)
        with self.assertRaisesMessage(ValueError, NEW_GATE_ADVENTURE):
            BookingService.create_booking(self.user, {
                "adventure_id": str(adventure.id),
                "check_in": "2026-11-02", "check_out": "2026-11-04",
                "spots": 5,  # 6 held + 5 > 10; legacy gate (0 + 5 <= 10) passes
            })
        booking = BookingService.create_booking(self.user, {
            "adventure_id": str(adventure.id),
            "check_in": "2026-11-02", "check_out": "2026-11-04",
            "spots": 4,  # 6 + 4 == 10: exactly at capacity is allowed
        })
        self.assertEqual(booking.items.get().quantity, 4)

    def test_vehicle_overlap_rejects_simultaneous_bookings(self):
        vehicle = _make_vehicle(self.city)  # is_available=True, untouched by _hold
        _hold(self.user, "VEHICLE", vehicle, "2026-11-01", "2026-11-03")
        with self.assertRaisesMessage(ValueError, NEW_GATE_VEHICLE):
            BookingService.create_booking(self.user, {
                "vehicle_id": str(vehicle.id),
                "check_in": "2026-11-02", "check_out": "2026-11-04",
            })
        # Same-day turnover is allowed by both gates (is_available still True).
        booking = BookingService.create_booking(self.user, {
            "vehicle_id": str(vehicle.id),
            "check_in": "2026-11-03", "check_out": "2026-11-05",
        })
        self.assertEqual(booking.status, "PENDING")


class OverlapGateRollbackTests(TestCase):
    """A failure AFTER the hotel branch (gate passed, counter decremented)
    must roll back the whole transaction: no Booking, no BookingItem, and the
    hotel counter restored. SQLite proves the transaction arithmetic; the
    crash-under-real-locks variant is PostgreSQL-only (see below)."""

    def setUp(self):
        self.city = _make_city()
        self.user = _make_user("overlap_rollback")

    def test_failed_overlap_gate_rolls_back_hotel_writes(self):
        hotel = _make_hotel(self.city, total_rooms=5, available_rooms=5)
        adventure = _make_adventure(self.city, max_capacity=10)
        _hold(self.user, "ADVENTURE", adventure, "2026-11-01", "2026-11-05", quantity=10)
        with self.assertRaisesMessage(ValueError, NEW_GATE_ADVENTURE):
            BookingService.create_booking(self.user, {
                "hotel_id": str(hotel.id),       # passes both hotel gates first
                "adventure_id": str(adventure.id),  # then fails the overlap gate
                "check_in": "2026-11-02", "check_out": "2026-11-04",
                "spots": 1,
            })
        hotel.refresh_from_db()
        self.assertEqual(hotel.available_rooms, 5)  # decrement rolled back
        self.assertEqual(Booking.objects.count(), 1)  # only the fixture hold
        self.assertEqual(BookingItem.objects.count(), 1)


@skipUnless(connection.vendor == "postgresql",
            "SELECT FOR UPDATE row-lock semantics require PostgreSQL; "
            "SQLite ignores row locks — report as BLOCKED, never as proven.")
class PostgresConcurrencyTests(TransactionTestCase):
    """Real-lock races. BLOCKED in this workspace (no PostgreSQL); runnable
    via docs/audit/WINDOWS_SETUP.md compose stack."""

    def setUp(self):
        self.city = _make_city()
        self.user = _make_user("overlap_pg")

    def _race(self, call_a, call_b):
        barrier = threading.Barrier(2, timeout=10)
        results = {}

        def runner(name, fn):
            try:
                barrier.wait()
                results[name] = ("ok", fn())
            except Exception as exc:  # noqa: BLE001 — recording the outcome
                results[name] = ("err", exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=runner, args=(n, f))
                   for n, f in (("a", call_a), ("b", call_b))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        return results

    def test_two_concurrent_bookings_for_last_room_yield_exactly_one_success(self):
        hotel = _make_hotel(self.city, total_rooms=1, available_rooms=1)

        def book():
            return BookingService.create_booking(_make_user(f"u{threading.get_ident()}"), {
                "hotel_id": str(hotel.id),
                "check_in": "2026-11-01", "check_out": "2026-11-03",
            })

        results = self._race(book, book)
        outcomes = sorted(kind for kind, _ in results.values())
        self.assertEqual(outcomes, ["err", "ok"])
        self.assertEqual(
            Booking.objects.filter(status="PENDING").count(), 1)

    def test_two_concurrent_vehicle_bookings_same_window_yield_exactly_one_success(self):
        vehicle = _make_vehicle(self.city)

        def book():
            return BookingService.create_booking(_make_user(f"v{threading.get_ident()}"), {
                "vehicle_id": str(vehicle.id),
                "check_in": "2026-11-01", "check_out": "2026-11-03",
            })

        results = self._race(book, book)
        outcomes = sorted(kind for kind, _ in results.values())
        self.assertEqual(outcomes, ["err", "ok"])
