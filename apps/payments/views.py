import stripe
from django.conf import settings
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status
from .services import StripeService
from apps.bookings.models import Booking


class CreateCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        booking_id = request.data.get('booking_id')
        try:
            booking = Booking.objects.get(
                id=booking_id,
                user=request.user,
                status='PENDING'
            )
            session = StripeService.create_checkout_session(booking)
            return Response({
                'checkout_url': session.url,
                'session_id': session.id,
            })
        except Booking.DoesNotExist:
            return Response(
                {'error': 'Booking not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class StripeWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

        try:
            StripeService.handle_webhook(payload, sig_header)
            return HttpResponse(status=200)
        except ValueError as e:
            return HttpResponse(str(e), status=400)


class PaymentSuccessView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'message': 'Payment successful! Booking confirmed.'})


class PaymentCancelView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'message': 'Payment cancelled.'})
