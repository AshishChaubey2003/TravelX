"""
Regression test lock for F-031: Booking and BookingItem admin surfaces must
refuse add + delete + modification by any admin user, including superuser.

Pre-Batch-D-prep behaviour: BookingAdmin had no `has_add_permission` /
`has_delete_permission` overrides, so a superuser could create, edit, or
delete a Booking from the admin — silently diverging from Payment,
OutboxEvent, and consumer invariants. These tests fail against that
behaviour and pass after Batch D-prep.
"""
from datetime import date
from decimal import Decimal

from django.contrib.admin.sites import site
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from apps.bookings.admin import BookingAdmin, BookingItemAdmin
from apps.bookings.models import Booking, BookingItem


def _superuser():
    return User.objects.create_superuser(
        username='admin', email='admin@example.com', password='x',
    )


class BookingAdminIsReadOnlyTests(TestCase):
    def setUp(self):
        self.user = _superuser()
        self.rf = RequestFactory()
        self.booking_admin = BookingAdmin(Booking, site)
        self.item_admin = BookingItemAdmin(BookingItem, site)
        req = self.rf.get('/admin/')
        req.user = self.user
        self.req = req

    def test_booking_add_is_refused_even_for_superuser(self):
        self.assertFalse(self.booking_admin.has_add_permission(self.req))

    def test_booking_delete_is_refused_even_for_superuser(self):
        self.assertFalse(self.booking_admin.has_delete_permission(self.req))

    def test_booking_change_is_refused_on_mutating_methods(self):
        get_req = self.rf.get('/admin/'); get_req.user = self.user
        post_req = self.rf.post('/admin/'); post_req.user = self.user
        self.assertTrue(self.booking_admin.has_change_permission(get_req))
        self.assertFalse(self.booking_admin.has_change_permission(post_req))

    def test_bookingitem_add_is_refused_even_for_superuser(self):
        self.assertFalse(self.item_admin.has_add_permission(self.req))

    def test_bookingitem_delete_is_refused_even_for_superuser(self):
        self.assertFalse(self.item_admin.has_delete_permission(self.req))

    def test_bookingitem_change_is_refused_on_mutating_methods(self):
        post_req = self.rf.post('/admin/'); post_req.user = self.user
        self.assertFalse(self.item_admin.has_change_permission(post_req))

    def test_every_booking_field_is_in_readonly_fields(self):
        """Pin that no model field is accidentally left editable."""
        model_fields = {f.name for f in Booking._meta.fields}
        readonly = set(self.booking_admin.readonly_fields)
        missing = model_fields - readonly
        self.assertEqual(
            missing, set(),
            f'Booking fields NOT in readonly_fields: {sorted(missing)}',
        )

    def test_every_bookingitem_field_is_in_readonly_fields(self):
        model_fields = {f.name for f in BookingItem._meta.fields}
        readonly = set(self.item_admin.readonly_fields)
        missing = model_fields - readonly
        self.assertEqual(
            missing, set(),
            f'BookingItem fields NOT in readonly_fields: {sorted(missing)}',
        )


class BookingAdminURLsAreRefusedEndToEndTests(TestCase):
    """
    End-to-end: hit the admin URLs with the Django test client as a
    superuser. GET detail pages render; POST attempts return 403.
    """
    def setUp(self):
        self.user = _superuser()
        self.client.force_login(self.user)
        self.booking = Booking.objects.create(
            user=self.user, status='PENDING', total_amount=Decimal('100'),
            check_in=date(2030, 1, 1), check_out=date(2030, 1, 3),
        )

    def test_booking_add_page_returns_403(self):
        response = self.client.get('/admin/bookings/booking/add/')
        self.assertEqual(response.status_code, 403)

    def test_booking_delete_page_returns_403(self):
        response = self.client.get(
            f'/admin/bookings/booking/{self.booking.pk}/delete/'
        )
        self.assertEqual(response.status_code, 403)

    def test_bookingitem_add_page_returns_403(self):
        response = self.client.get('/admin/bookings/bookingitem/add/')
        self.assertEqual(response.status_code, 403)
