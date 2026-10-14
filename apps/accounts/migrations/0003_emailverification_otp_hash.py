# F-010 — OTP hashing migration (one-shot model; REVIEWED, NOT APPLIED to any
# real database from the audit workspace).
#
# Forward: (1) add otp_hash; (2) hash every ACTIVE plaintext OTP into it with
# Argon2 and blank the plaintext. Rows with an empty otp are untouched (the
# filter excludes them), so the backfill is safe on empty values and
# re-runnable. Active OTPs therefore SURVIVE the migration: a user
# mid-verification can still submit their code afterwards.
#
# Reverse: removes the otp_hash column only. Hashes CANNOT be turned back
# into plaintext, so after a rollback every in-flight OTP is unusable — the
# cost is bounded by the 10-minute OTP lifetime: affected users press
# "Resend OTP". (The legacy `otp` column itself is kept by this migration;
# dropping it is a separate, later contract migration gated on confirming
# the production deployment model.)
#
# Deployment requirement (stop-the-world, matching docker-compose.yml): the
# argon2-cffi package must be installed (image rebuilt) BEFORE the migrate
# one-shot runs — make_password(..., 'argon2') raises ImproperlyConfigured
# without it — and no pre-0003 code may run against the post-0003 data (the
# compose flow guarantees both: build, down, migrate gate, up).

from django.contrib.auth.hashers import make_password
from django.db import migrations, models


def hash_active_otps(apps, schema_editor):
    EmailVerification = apps.get_model("accounts", "EmailVerification")
    # Only rows holding a live plaintext OTP; empty OTPs are skipped safely.
    for row in EmailVerification.objects.exclude(otp="").iterator(chunk_size=500):
        row.otp_hash = make_password(row.otp, hasher="argon2")
        row.otp = ""
        row.save(update_fields=["otp_hash", "otp"])


def reverse_noop(apps, schema_editor):
    # Deliberate no-op: plaintext cannot be recovered from Argon2 hashes.
    # Reversing the migration drops otp_hash (AddField reverse); users with
    # an in-flight OTP must use "Resend OTP".
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_alter_emailverification_expires_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="emailverification",
            name="otp_hash",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.RunPython(hash_active_otps, reverse_noop),
    ]
