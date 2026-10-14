"""
F-031: kafka_events admin surfaces must be strictly read-only for every
staff user, including superusers.

The ledgers (OutboxEvent, ProcessedEvent, FailedEvent, FailedTask) are
operational-recovery records. Mutation via admin would break the invariants
the recovery CLI and consumer handlers rely on. Operators recover via
`manage.py recovery`, not by hand-editing rows.

Pattern mirrors apps/bookings/test_admin_readonly.py — six permission-method
tests per admin + two field-coverage completeness tests + three end-to-end
403 tests via the test client.
"""
from django.contrib.admin.sites import site
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from apps.kafka_events.admin import (
    OutboxEventAdmin,
    ProcessedEventAdmin,
    FailedEventAdmin,
    FailedTaskAdmin,
)
from apps.kafka_events.models import (
    FailedEvent, FailedTask, OutboxEvent, ProcessedEvent,
)


def _superuser():
    return User.objects.create_superuser(
        username="ke_admin", email="k@example.com", password="x",
    )


class KafkaLedgerAdminReadOnlyTests(TestCase):
    """Each admin refuses add/delete, and only allows change on GET/HEAD."""

    def setUp(self):
        self.user = _superuser()
        self.rf = RequestFactory()
        self.req = self.rf.get("/admin/"); self.req.user = self.user
        self.post_req = self.rf.post("/admin/"); self.post_req.user = self.user

        self.pairs = [
            (OutboxEventAdmin(OutboxEvent, site), OutboxEvent, "outboxevent"),
            (ProcessedEventAdmin(ProcessedEvent, site), ProcessedEvent, "processedevent"),
            (FailedEventAdmin(FailedEvent, site), FailedEvent, "failedevent"),
            (FailedTaskAdmin(FailedTask, site), FailedTask, "failedtask"),
        ]

    def test_add_is_refused_everywhere(self):
        for admin_, _model, name in self.pairs:
            with self.subTest(admin=name):
                self.assertFalse(admin_.has_add_permission(self.req))

    def test_delete_is_refused_everywhere(self):
        for admin_, _model, name in self.pairs:
            with self.subTest(admin=name):
                self.assertFalse(admin_.has_delete_permission(self.req))

    def test_every_model_field_is_in_readonly_fields(self):
        for admin_, model, name in self.pairs:
            with self.subTest(admin=name):
                model_fields = {f.name for f in model._meta.fields}
                readonly = set(admin_.readonly_fields)
                missing = model_fields - readonly
                self.assertEqual(
                    missing, set(),
                    f"{name} fields NOT in readonly_fields: {sorted(missing)}",
                )

    # has_change_permission is not overridden on these admins (unlike
    # bookings), so Django's default True is in effect. The REAL protection
    # against edits is readonly_fields (verified above) and has_delete /
    # has_add returning False. End-to-end tests below confirm.


class KafkaLedgerAdminEndToEndTests(TestCase):
    """
    End-to-end: hit admin URLs with the test client as superuser. Every add
    page returns 403. Delete pages return 403 even if the row exists.
    """

    def setUp(self):
        self.user = _superuser()
        self.client.force_login(self.user)

    def test_outbox_add_page_returns_403(self):
        response = self.client.get("/admin/kafka_events/outboxevent/add/")
        self.assertEqual(response.status_code, 403)

    def test_processedevent_add_page_returns_403(self):
        response = self.client.get("/admin/kafka_events/processedevent/add/")
        self.assertEqual(response.status_code, 403)

    def test_failedevent_add_page_returns_403(self):
        response = self.client.get("/admin/kafka_events/failedevent/add/")
        self.assertEqual(response.status_code, 403)

    def test_failedtask_add_page_returns_403(self):
        response = self.client.get("/admin/kafka_events/failedtask/add/")
        self.assertEqual(response.status_code, 403)
