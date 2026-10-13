import razorpay
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.db import transaction
from rest_framework import status
from apps.kafka_events.outbox import enqueue_event
from apps.kafka_events.policy import can_transition
from apps.kafka_events.topics import TOPIC_PAYMENT_SUCCESS
from .services import PaymentNotPayableError, RazorpayService
from .models import Payment
from apps.bookings.models import Booking
from apps.core.flow_health import record_flow


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
            response = Response({
                'order_id': order['id'],
                'amount': order['amount'],
                'currency': order['currency'],
                'key_id': settings.RAZORPAY_KEY_ID,
                'booking_id': str(booking.id),
                'user_email': request.user.email,
                'user_name': request.user.username,
            })
            record_flow('payment_order', 'success', booking_id=booking.id, order_id=order['id'])
            return response
        except Booking.DoesNotExist:
            record_flow('payment_order', 'rejected', booking_id=booking_id, reason='booking_not_found')
            return Response({'error': 'Booking not found'}, status=404)
        except DjangoValidationError:
            record_flow('payment_order', 'rejected', booking_id=booking_id, reason='invalid_booking_id')
            return Response({'error': 'Invalid booking id'}, status=400)
        except PaymentNotPayableError as exc:
            record_flow('payment_order', 'rejected', booking_id=booking_id, reason='not_payable')
            return Response({'error': str(exc)}, status=400)
        except Exception as e:
            # The cause is logged with a traceback; the client gets a generic
            # message instead of an internal exception string.
            record_flow(
                'payment_order', 'failure', booking_id=booking_id,
                reason=type(e).__name__, exc_info=True,
            )
            return Response({'error': 'Could not create payment order'}, status=400)


class VerifyRazorpayPaymentView(APIView):
    """
    Browser-submitted payment verification.

    The Payment row's own transition to SUCCESS is the single deduplication
    gate shared with the Razorpay webhook: whichever path arrives first emits
    the one and only payment.success event, so the two can never both charge
    or both confirm the same payment.

    Outcome labelling, after a VALID signature: every way of failing to record
    the payment is a `failure`, never a `rejected`. A valid signature means the
    gateway took money, so an unrecordable payment needs a human to look. This
    is deliberate and test-enforced by
    apps/core/test_flow_health.py::test_verify_valid_signature_but_no_payment_row_is_a_failure.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        razorpay_order_id = request.data.get('razorpay_order_id')
        razorpay_payment_id = request.data.get('razorpay_payment_id')
        razorpay_signature = request.data.get('razorpay_signature')
        booking_id = request.data.get('booking_id')

        if not RazorpayService.verify_payment(
            razorpay_order_id, razorpay_payment_id, razorpay_signature
        ):
            record_flow(
                'payment_verify', 'rejected',
                booking_id=booking_id, order_id=razorpay_order_id,
                reason='invalid_signature',
            )
            return Response({'error': 'Invalid payment signature'}, status=400)

        booking_payable = False

        try:
            with transaction.atomic():
                booking = Booking.objects.select_for_update().get(
                    id=booking_id, user=request.user
                )
                payment = Payment.objects.select_for_update().get(booking=booking)

                if payment.stripe_session_id != razorpay_order_id:
                    record_flow(
                        'payment_verify', 'rejected',
                        booking_id=booking_id, order_id=razorpay_order_id,
                        reason='order_booking_mismatch',
                    )
                    return Response(
                        {'error': 'This payment order does not match the specified booking.'},
                        status=400,
                    )

                if payment.status in ('REFUND_PENDING', 'REFUNDED'):
                    record_flow(
                        'payment_verify', 'rejected',
                        booking_id=booking_id, order_id=razorpay_order_id,
                        reason='already_refunded',
                    )
                    return Response(
                        {'error': 'This payment has already been refunded.'},
                        status=400,
                    )

                # Decided before any write so the outcome is unambiguous.
                booking_payable = (
                    booking.status == 'PAID'
                    or can_transition(booking.status, 'PAID')
                )

                if payment.status != 'SUCCESS':
                    payment.status = 'SUCCESS'
                    payment.stripe_payment_intent_id = razorpay_payment_id
                    payment.save(update_fields=['status', 'stripe_payment_intent_id'])

                    # G08: written to the transactional outbox inside this same
                    # transaction. If it raises, the payment transition rolls
                    # back rather than committing without its event.
                    enqueue_event(TOPIC_PAYMENT_SUCCESS, {
                        'booking_id': str(booking.id),
                        'user_id': str(booking.user.id),
                        'user_email': booking.user.email,
                        'amount': str(payment.amount),
                        'stripe_session_id': payment.stripe_session_id,
                    })

                if booking_payable and booking.status != 'PAID':
                    booking.status = 'PAID'
                    booking.save(update_fields=['status'])

        except Booking.DoesNotExist:
            record_flow(
                'payment_verify', 'failure',
                booking_id=booking_id, order_id=razorpay_order_id,
                reason='booking_not_found',
            )
            return Response({'error': 'Payment could not be recorded'}, status=400)
        except Payment.DoesNotExist:
            record_flow(
                'payment_verify', 'failure',
                booking_id=booking_id, order_id=razorpay_order_id,
                reason='payment_not_found',
            )
            return Response({'error': 'Payment could not be recorded'}, status=400)
        except DjangoValidationError:
            record_flow(
                'payment_verify', 'failure',
                booking_id=booking_id, order_id=razorpay_order_id,
                reason='invalid_booking_id',
            )
            return Response({'error': 'Payment could not be recorded'}, status=400)
        except Exception as e:
            record_flow(
                'payment_verify', 'failure',
                booking_id=booking_id, order_id=razorpay_order_id,
                reason=type(e).__name__, exc_info=True,
            )
            return Response({'error': 'Payment could not be recorded'}, status=400)

        if not booking_payable:
            # The payment IS recorded, because the money is real, but the
            # booking cannot be marked paid - it was cancelled meanwhile, for
            # example. Previously this silently overwrote the booking status.
            record_flow(
                'payment_verify', 'failure',
                booking_id=booking_id, order_id=razorpay_order_id,
                reason='booking_not_payable',
            )
            return Response(
                {'error': 'Payment recorded, but this booking cannot be marked paid.'},
                status=400,
            )

        record_flow(
            'payment_verify', 'success',
            booking_id=booking_id, order_id=razorpay_order_id,
        )
        return Response({'success': True, 'message': 'Payment verified!'})


class RefundView(APIView):
    """
    Refund INITIATION only.

    Razorpay accepting a refund request does not mean the refund completed, so
    this records REFUND_PENDING and leaves the booking PAID. The booking is
    cancelled and inventory restored only when the refund.processed webhook
    confirms completion - which also makes repeated confirmations unable to
    restore inventory twice.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        booking_id = request.data.get('booking_id')

        try:
            with transaction.atomic():
                booking = Booking.objects.select_for_update().get(
                    id=booking_id,
                    user=request.user,
                    status='PAID'
                )
                payment = Payment.objects.select_for_update().get(booking=booking)

                if not payment.stripe_payment_intent_id:
                    record_flow('refund', 'rejected', booking_id=booking_id, reason='no_payment_reference')
                    return Response({'error': 'No payment found for refund'}, status=400)

                if payment.status == 'REFUNDED':
                    record_flow('refund', 'rejected', booking_id=booking_id, reason='already_refunded')
                    return Response(
                        {'error': 'This payment has already been refunded.'}, status=400
                    )

                if payment.status == 'REFUND_PENDING':
                    record_flow('refund', 'rejected', booking_id=booking_id, reason='refund_in_progress')
                    return Response(
                        {'error': 'A refund is already in progress.'}, status=400
                    )

                if payment.status != 'SUCCESS':
                    record_flow('refund', 'rejected', booking_id=booking_id, reason='not_refundable')
                    return Response(
                        {'error': 'This payment is not in a refundable state.'}, status=400
                    )

                payment_pk = payment.pk
                refund_target = payment

        except Booking.DoesNotExist:
            record_flow('refund', 'rejected', booking_id=booking_id, reason='booking_not_found')
            return Response({'error': 'Booking not found'}, status=404)
        except Payment.DoesNotExist:
            record_flow('refund', 'rejected', booking_id=booking_id, reason='payment_not_found')
            return Response({'error': 'No payment record for this booking'}, status=400)
        except DjangoValidationError:
            record_flow('refund', 'rejected', booking_id=booking_id, reason='invalid_booking_id')
            return Response({'error': 'Invalid booking id'}, status=400)

        # Outside the transaction: an external API call cannot participate in a
        # database transaction, and holding a row lock across a network call
        # would be worse than not holding one.
        try:
            refund = RazorpayService.initiate_refund(refund_target)
        except ValueError:
            record_flow('refund', 'failure', booking_id=booking_id, reason='gateway_error')
            return Response({'error': 'Refund could not be initiated'}, status=400)
        except Exception as e:
            record_flow(
                'refund', 'failure', booking_id=booking_id,
                reason=type(e).__name__, exc_info=True,
            )
            return Response({'error': 'Refund could not be initiated'}, status=400)

        # Razorpay returns a dict. Anything else - an SDK change, or a
        # mock in tests - must never reach a CharField, where Django would
        # treat it as a query expression.
        refund_id = refund.get('id') if isinstance(refund, dict) else None
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=payment_pk)
            # If refund.processed already landed in this window it has set
            # REFUNDED; do not move it back to REFUND_PENDING.
            if payment.status == 'SUCCESS':
                payment.status = 'REFUND_PENDING'
                if refund_id:
                    payment.razorpay_refund_id = str(refund_id)[:200]
                payment.save(update_fields=['status', 'razorpay_refund_id'])

        record_flow('refund', 'success', booking_id=booking_id, reason='initiated')
        return Response({
            'success': True,
            'message': 'Refund initiated. Razorpay will confirm it shortly.',
        })


class PaymentSuccessView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'message': 'Payment successful!'})


class PaymentCancelView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'message': 'Payment cancelled.'})
