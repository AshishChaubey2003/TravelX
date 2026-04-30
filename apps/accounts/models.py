from django.db import models
from django.contrib.auth.models import User
import random
import string
from django.utils import timezone
from datetime import timedelta


class EmailVerification(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='email_verification')
    otp = models.CharField(max_length=6, default='')
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=timezone.now)  # ← fix

    def generate_otp(self):
        self.otp = ''.join(random.choices(string.digits, k=6))
        self.expires_at = timezone.now() + timedelta(minutes=10)
        self.save()
        return self.otp

    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"{self.user.email} - {'Verified' if self.is_verified else 'Pending'}"