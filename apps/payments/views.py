import razorpay
from django.conf import settings
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status
from .services import RazorpayService
from .models import Payment
from apps.bookings.models import Booking


class CreateRazorpayOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        booking_id = request.data.get('booking_id')
        try:
            booking = Booking.objects.get(
                id=booking_id,
                user=request.user,
                status='PENDING'
            )
            order = RazorpayService.create_order(booking)
            return Response({
                'order_id': order['id'],
                'amount': order['amount'],
                'currency': order['currency'],
                'key_id': settings.RAZORPAY_KEY_ID,
                'booking_id': str(booking.id),
                'user_email': request.user.email,
                'user_name': request.user.username,
            })
        except Booking.DoesNotExist:
            return Response({'error': 'Booking not found'}, status=404)
        except Exception as e:
            return Response({'error': str(e)}, status=400)


class VerifyRazorpayPaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        razorpay_order_id = request.data.get('razorpay_order_id')
        razorpay_payment_id = request.data.get('razorpay_payment_id')
        razorpay_signature = request.data.get('razorpay_signature')
        booking_id = request.data.get('booking_id')

        is_valid = RazorpayService.verify_payment(
            razorpay_order_id, razorpay_payment_id, razorpay_signature
        )

        if is_valid:
            try:
                booking = Booking.objects.get(id=booking_id, user=request.user)
                booking.status = 'PAID'
                booking.save()

                payment = Payment.objects.get(booking=booking)
                payment.status = 'SUCCESS'
                payment.stripe_payment_intent_id = razorpay_payment_id
                payment.save()

                return Response({'success': True, 'message': 'Payment verified!'})
            except Exception as e:
                return Response({'error': str(e)}, status=400)
        else:
            return Response({'error': 'Invalid payment signature'}, status=400)


class RefundView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        booking_id = request.data.get('booking_id')
        try:
            booking = Booking.objects.get(
                id=booking_id,
                user=request.user,
                status='PAID'
            )
            payment = Payment.objects.get(booking=booking)

            if not payment.stripe_payment_intent_id:
                return Response({'error': 'No payment found for refund'}, status=400)

            RazorpayService.process_refund(payment)
            booking.status = 'CANCELLED'
            booking.save()

            return Response({'success': True, 'message': 'Refund processed!'})
        except Booking.DoesNotExist:
            return Response({'error': 'Booking not found'}, status=404)
        except Exception as e:
            return Response({'error': str(e)}, status=400)


class PaymentSuccessView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'message': 'Payment successful!'})


class PaymentCancelView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'message': 'Payment cancelled.'})