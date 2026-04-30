from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.conf import settings
from .serializers import RegisterSerializer, VerifyOTPSerializer
from .models import EmailVerification


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
            except Exception as e:
                user.delete()
                return Response(
                    {'error': f'Email send failed: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            return Response({
                'message': 'Registration successful! Check your email for OTP.',
                'email': user.email
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifyOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp = serializer.validated_data['otp']

            try:
                user = User.objects.get(email=email)
                verification = EmailVerification.objects.get(user=user)

                if verification.is_verified:
                    return Response({'message': 'Email already verified!'})

                if verification.is_expired():
                    return Response(
                        {'error': 'OTP expired! Please register again.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                if verification.otp != otp:
                    return Response(
                        {'error': 'Invalid OTP!'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Verify karo
                verification.is_verified = True
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

    def post(self, request):
        email = request.data.get('email')
        try:
            user = User.objects.get(email=email, is_active=False)
            verification = EmailVerification.objects.get(user=user)
            otp = verification.generate_otp()

            send_mail(
                subject='TravelX — New OTP',
                message=f'Your new OTP is: {otp}\n\nValid for 10 minutes.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )

            return Response({'message': 'New OTP sent to your email!'})

        except User.DoesNotExist:
            return Response(
                {'error': 'User not found or already verified!'},
                status=status.HTTP_404_NOT_FOUND
            )