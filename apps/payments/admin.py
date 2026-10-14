"""
F-031: operational visibility for Payment and WebhookEvent. Everything is
read-only here — admin is for inspection, not state recovery (use
`manage.py recovery` for that).
"""
from django.contrib import admin
from .models import Payment, WebhookEvent


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'booking', 'amount', 'currency', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'currency')
    search_fields = ('id', 'booking__id', 'stripe_session_id', 'stripe_payment_intent_id')
    date_hierarchy = 'created_at'
    readonly_fields = tuple(f.name for f in Payment._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'event_type', 'status', 'razorpay_payment_id', 'received_at')
    list_filter = ('event_type', 'status')
    search_fields = ('event_key', 'razorpay_payment_id', 'note')
    date_hierarchy = 'received_at'
    readonly_fields = tuple(f.name for f in WebhookEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
