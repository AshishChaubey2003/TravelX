"""
F-031: operational visibility — admin surfaces for the outbox and dead-letter
ledgers. Read-only. Use `manage.py recovery` to actually replay.
"""
from django.contrib import admin

from .models import FailedEvent, FailedTask, OutboxEvent, ProcessedEvent


@admin.register(OutboxEvent)
class OutboxEventAdmin(admin.ModelAdmin):
    list_display = ("id", "topic", "status", "attempts", "created_at", "published_at", "next_attempt_at")
    list_filter = ("status", "topic")
    search_fields = ("event_id", "key", "last_error")
    date_hierarchy = "created_at"
    readonly_fields = tuple(f.name for f in OutboxEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProcessedEvent)
class ProcessedEventAdmin(admin.ModelAdmin):
    list_display = ("id", "topic", "event_key", "processed_at")
    list_filter = ("topic",)
    search_fields = ("event_key",)
    date_hierarchy = "processed_at"
    readonly_fields = tuple(f.name for f in ProcessedEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FailedEvent)
class FailedEventAdmin(admin.ModelAdmin):
    list_display = ("id", "topic", "status", "attempts", "created_at", "updated_at")
    list_filter = ("status", "topic")
    search_fields = ("event_key", "last_error")
    date_hierarchy = "created_at"
    readonly_fields = tuple(f.name for f in FailedEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FailedTask)
class FailedTaskAdmin(admin.ModelAdmin):
    # FailedTask has created_at only; no updated_at on this model (see models.py).
    list_display = ("id", "task_name", "status", "created_at")
    list_filter = ("status", "task_name")
    search_fields = ("task_id", "task_name")
    date_hierarchy = "created_at"
    readonly_fields = tuple(f.name for f in FailedTask._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
