import logging
import secrets

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.conf import settings
from django.db import transaction
from .serializers import RegisterSerializer, ResendOTPSerializer, VerifyOTPSerializer
from .models import EmailVerification

logger = logging.getLogger('travelx.request')


def _otp_matches(stored, supplied):
    """Constant-time OTP comparison. An empty/unset stored OTP never matches."""
    if not stored or not supplied:
        return False
    return secrets.compare_digest(stored.encode('utf-8'), supplied.encode('utf-8'))


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()

            # OTP banao aur email bhejo
            verification, _ = EmailVerification.objects.get_or_create(user=user)
            otp = verification.generate_otp()

            try:
                send_mail(
                    subject='TravelX — Verify Your Email',
                    message=f'''
Hi {user.username}!

Welcome to TravelX! 🌍

Your verification OTP is: {otp}

This OTP is valid for 10 minutes.

Team TravelX
                    ''',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
            except Exception as exc:
                # Capture the id first: delete() clears the instance pk.
                user_id = user.id
                user.delete()
                # Log only the exception class: SMTP error text can carry hostnames or
                # credentials, and the OTP / password must never reach the logs.
                logger.error(
                    "RegisterView: failed to send verification email for user_id=%s error_type=%s",
                    user_id, type(exc).__name__,
                )
                return Response(
                    {'error': 'Registration could not be completed. Please try again later.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            return Response({
                'message': 'Registration successful! Check your email for OTP.',
                'email': user.email
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifyOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp_verify'

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp = serializer.validated_data['otp']

            try:
                # Case-insensitive lookup; if legacy data holds several accounts whose
                # emails differ only by case, prefer the pending (inactive) one.
                user = (
                    User.objects.filter(email__iexact=email)
                    .order_by('is_active', 'id')
                    .first()
                )
                if user is None:
                    raise User.DoesNotExist
                verification = EmailVerification.objects.filter(user=user).first()
                if verification is None:
                    if user.is_active:
                        return Response({'message': 'Email already verified!'})
                    return Response(
                        {'error': 'Verification record not found! Please request a new OTP.'},
                        status=status.HTTP_404_NOT_FOUND
                    )

                if verification.is_verified:
                    return Response({'message': 'Email already verified!'})

                if verification.is_expired():
                    return Response(
                        {'error': 'OTP expired! Please register again.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                if not _otp_matches(verification.otp, otp):
                    return Response(
                        {'error': 'Invalid OTP!'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Verify karo
                with transaction.atomic():
                    verification.is_verified = True
                    verification.otp = ''  # single use
                    verification.save()
                    user.is_active = True
                    user.save()

                return Response({
                    'message': 'Email verified successfully! You can now login. ✅'
                })

            except User.DoesNotExist:
                return Response(
                    {'error': 'User not found!'},
                    status=status.HTTP_404_NOT_FOUND
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ResendOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp_resend'

    def post(self, request):
        serializer = ResendOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        email = serializer.validated_data['email']

        user_id = None
        verification = None
        previous = None
        try:
            user = (
                User.objects.filter(email__iexact=email, is_active=False)
                .order_by('id')
                .first()
            )
            if user is None:
                raise User.DoesNotExist
            user_id = user.id
            verification, _ = EmailVerification.objects.get_or_create(user=user)
            if verification.is_verified:
                # Verified but inactive (e.g. deactivated): a fresh OTP would be useless.
                raise User.DoesNotExist
            previous = (verification.otp, verification.expires_at)
            otp = verification.generate_otp()

            send_mail(
                subject='TravelX — New OTP',
                message=f'Your new OTP is: {otp}\n\nValid for 10 minutes.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )

            return Response({'message': 'New OTP sent to your email!'})

        except User.DoesNotExist:
            return Response(
                {'error': 'User not found or already verified!'},
                status=status.HTTP_404_NOT_FOUND
            )

        except Exception as exc:
            # Sending (or persisting) failed: put the previous OTP back so the code the
            # user last received still works. Never echo exception details to the client.
            if verification is not None and previous is not None:
                EmailVerification.objects.filter(pk=verification.pk).update(
                    otp=previous[0], expires_at=previous[1]
                )
            logger.error(
                "ResendOTPView: failed to send new OTP for user_id=%s error_type=%s",
                user_id, type(exc).__name__,
            )
            return Response(
                {'error': 'Could not send OTP. Please try again later.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )