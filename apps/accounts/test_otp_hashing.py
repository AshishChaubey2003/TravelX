"""
F-010 — Argon2 OTP hashing: storage contract, migration backfill, and the
password-hasher policy pin (PBKDF2 stays preferred; user passwords
unaffected).

The migration backfill is tested by calling the migration module's own
RunPython function against the live test schema (which already includes
0003, so the otp column still exists and can be seeded the way a
pre-migration row would look). This proves the backfill logic — it is NOT a
real-database migration run.
"""
from importlib import import_module

from django.apps import apps as live_apps
from django.conf import settings
from django.contrib.auth.hashers import (
    check_password,
    get_hasher,
    identify_hasher,
    make_password,
)
from django.contrib.auth.models import User
from django.test import TestCase

from apps.accounts.models import EmailVerification

backfill = import_module("apps.accounts.migrations.0003_emailverification_otp_hash")


def _make_verification(username, **fields):
    user = User.objects.create_user(
        username=username, email=f"{username}@example.com",
        password="UserPw!2345", is_active=False,
    )
    return EmailVerification.objects.create(user=user, **fields)


class OTPStorageContractTests(TestCase):
    def test_generated_otp_is_not_stored_in_plaintext(self):
        verification = _make_verification("store_user")
        plaintext = verification.generate_otp()
        verification.refresh_from_db()
        self.assertEqual(verification.otp, "")
        self.assertNotIn(plaintext, verification.otp_hash)
        self.assertTrue(verification.otp_hash.startswith("argon2"))
        self.assertTrue(check_password(plaintext, verification.otp_hash))

    def test_wrong_otp_fails_and_correct_otp_succeeds(self):
        verification = _make_verification("match_user")
        plaintext = verification.generate_otp()
        wrong = "000000" if plaintext != "000000" else "111111"
        self.assertFalse(verification.otp_matches(wrong))
        self.assertTrue(verification.otp_matches(plaintext))

    def test_empty_and_missing_values_never_match(self):
        verification = _make_verification("empty_user")
        self.assertFalse(verification.otp_matches(""))     # nothing stored yet
        self.assertFalse(verification.otp_matches("123456"))
        verification.generate_otp()
        self.assertFalse(verification.otp_matches(""))
        self.assertFalse(verification.otp_matches(None))

    def test_consume_otp_wipes_hash_and_plaintext(self):
        verification = _make_verification("consume_user")
        plaintext = verification.generate_otp()
        verification.consume_otp()
        verification.save()
        verification.refresh_from_db()
        self.assertEqual(verification.otp, "")
        self.assertEqual(verification.otp_hash, "")
        self.assertFalse(verification.otp_matches(plaintext))  # single use

    def test_resend_rotates_the_hash(self):
        verification = _make_verification("rotate_user")
        first = verification.generate_otp()
        first_hash = verification.otp_hash
        second = verification.generate_otp()
        self.assertNotEqual(first_hash, verification.otp_hash)
        self.assertFalse(verification.otp_matches(first) and first != second)
        self.assertTrue(verification.otp_matches(second))


class MigrationBackfillTests(TestCase):
    """Drives the 0003 RunPython forward function on rows shaped like
    pre-migration data (plaintext set, hash empty)."""

    def test_backfill_hashes_active_otps_and_clears_plaintext(self):
        live = _make_verification("mig_live")
        EmailVerification.objects.filter(pk=live.pk).update(
            otp="314159", otp_hash="")

        backfill.hash_active_otps(live_apps, None)

        live.refresh_from_db()
        self.assertEqual(live.otp, "")
        self.assertTrue(live.otp_hash.startswith("argon2"))
        self.assertTrue(check_password("314159", live.otp_hash))
        # The user's in-flight code still verifies through the model API:
        self.assertTrue(live.otp_matches("314159"))

    def test_backfill_handles_empty_otps_safely_and_is_rerunnable(self):
        empty = _make_verification("mig_empty")          # otp == '' from birth
        done = _make_verification("mig_done")
        EmailVerification.objects.filter(pk=done.pk).update(
            otp="271828", otp_hash="")

        backfill.hash_active_otps(live_apps, None)
        done.refresh_from_db()
        first_hash = done.otp_hash

        backfill.hash_active_otps(live_apps, None)       # second run: no-op
        empty.refresh_from_db()
        done.refresh_from_db()
        self.assertEqual(empty.otp, "")
        self.assertEqual(empty.otp_hash, "")             # untouched
        self.assertEqual(done.otp_hash, first_hash)      # not re-hashed


class PasswordHasherPolicyTests(TestCase):
    def test_pbkdf2_remains_the_preferred_password_hasher(self):
        self.assertEqual(
            settings.PASSWORD_HASHERS[0],
            "django.contrib.auth.hashers.PBKDF2PasswordHasher",
        )
        self.assertEqual(get_hasher().algorithm, "pbkdf2_sha256")

    def test_new_user_passwords_are_still_pbkdf2(self):
        user = User.objects.create_user(
            username="pw_user", email="pw@example.com", password="UserPw!2345")
        self.assertEqual(identify_hasher(user.password).algorithm, "pbkdf2_sha256")

    def test_existing_pbkdf2_password_hashes_remain_verifiable(self):
        user = User.objects.create_user(
            username="old_pw_user", email="old@example.com", password="UserPw!2345")
        stored = user.password  # a PBKDF2 hash, as before this change
        self.assertTrue(check_password("UserPw!2345", stored))
        # And logging in does not silently re-hash it to argon2 (PBKDF2 is
        # still preferred, so must_update stays False):
        self.assertTrue(user.check_password("UserPw!2345"))
        user.refresh_from_db()
        self.assertEqual(identify_hasher(user.password).algorithm, "pbkdf2_sha256")

    def test_argon2_is_available_for_explicit_use_only(self):
        hashed = make_password("123456", hasher="argon2")
        self.assertTrue(hashed.startswith("argon2"))
        self.assertTrue(check_password("123456", hashed))
