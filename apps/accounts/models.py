from django.db import models
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
import secrets
from django.utils import timezone
from datetime import timedelta


class EmailVerification(models.Model):
    """
    F-010: OTPs are stored as Argon2 hashes (otp_hash), never in plaintext.

    The legacy plaintext column `otp` is KEPT (always written as '') until a
    separately-approved contract migration removes it: dropping the column is
    only safe once the production deployment model (stop-the-world vs
    rolling) is confirmed — see docs/audit/PROPOSED_DIFFS_V2.md §F-010.
    Migration 0003 backfills any live plaintext OTPs into otp_hash and blanks
    the plaintext; its reverse CANNOT restore plaintext from hashes (users
    mid-verification after a rollback simply press "Resend OTP").
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='email_verification')
    otp = models.CharField(max_length=6, default='')      # legacy; always '' now
    otp_hash = models.CharField(max_length=255, default='', blank=True)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=timezone.now)  # ← fix

    def generate_otp(self):
        """Create a fresh 6-digit OTP; store ONLY its Argon2 hash. Returns
        the plaintext for the (synchronous) verification email — the only
        place it may appear. Never log it."""
        plaintext = f'{secrets.randbelow(10 ** 6):06d}'
        self.otp = ''  # plaintext is never stored (and any legacy value dies here)
        self.otp_hash = make_password(plaintext, hasher='argon2')
        self.expires_at = timezone.now() + timedelta(minutes=10)
        self.save()
        return plaintext

    def otp_matches(self, supplied):
        """
        Verify a supplied OTP. Empty/unset values never match.

        Prefers the hash (check_password; Argon2 verification is
        constant-time in the underlying library). The plaintext fallback
        exists ONLY for an un-backfilled legacy row (otp_hash empty, otp
        set) — after migration 0003 it is unreachable — and keeps the
        original constant-time compare.
        """
        if not supplied:
            return False
        if self.otp_hash:
            return check_password(supplied, self.otp_hash)
        if self.otp:
            return secrets.compare_digest(
                self.otp.encode('utf-8'), supplied.encode('utf-8'))
        return False

    def consume_otp(self):
        """Single use: wipe both the hash and the legacy plaintext field.
        The caller saves (inside its own transaction)."""
        self.otp = ''
        self.otp_hash = ''

    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"{self.user.email} - {'Verified' if self.is_verified else 'Pending'}"
