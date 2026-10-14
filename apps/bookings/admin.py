"""
F-031: Booking + BookingItem admin, now with the same read-only guarantees
as Payment + WebhookEvent (apps/payments/admin.py) and the kafka_events
ledgers (apps/kafka_events/admin.py).

Rationale: a Booking row carries status (PENDING/PAID/CANCELLED) and
total_amount; editing either from admin can quietly diverge from the
Payment and OutboxEvent records that reference it, breaking the invariants
that the Kafka consumer and recovery CLI rely on. Admin is for inspection
only; state recovery goes through `manage.py recovery` or the API.
"""
from django.contrib import admin

from .models import Booking, BookingItem


class BookingItemInline(admin.TabularInline):
    model = BookingItem
    extra = 0
    readonly_fields = tuple(f.name for f in BookingItem._meta.fields)

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'status', 'total_amount', 'check_in', 'check_out', 'created_at')
    list_filter = ('status',)
    search_fields = ('id', 'user__username', 'user__email', 'idempotency_key')
    date_hierarchy = 'created_at'
    readonly_fields = tuple(f.name for f in Booking._meta.fields)
    inlines = [BookingItemInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        # True for the list view and the detail view (fields are read-only
        # via `readonly_fields`), False for save() — Django enforces this.
        # Returning True keeps the detail page browsable; the readonly_fields
        # list is what actually prevents mutation.
        return request.method in ('GET', 'HEAD')


@admin.register(BookingItem)
class BookingItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'booking', 'item_type', 'item_name', 'price_at_booking', 'quantity')
    list_filter = ('item_type',)
    search_fields = ('booking__id', 'item_id', 'item_name')
    readonly_fields = tuple(f.name for f in BookingItem._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ('GET', 'HEAD')