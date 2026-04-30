import razorpay
from django.conf import settings
from .models import Payment
from apps.bookings.models import Booking

razorpay_client = razorpay.Client(
    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
)


class RazorpayService:

    @staticmethod
    def create_order(booking):
        amount = int(booking.total_amount * 100)

        order = razorpay_client.order.create({
            'amount': amount,
            'currency': 'INR',
            'receipt': str(booking.id)[:40],
            'notes': {
                'booking_id': str(booking.id),
                'user_email': booking.user.email,
            }
        })

        Payment.objects.get_or_create(
            booking=booking,
            defaults={
                'amount': booking.total_amount,
                'currency': 'inr',
                'status': 'PENDING',
                'stripe_session_id': order['id'],
            }
        )

        booking.stripe_session_id = order['id']
        booking.save()

        return order

    @staticmethod
    def verify_payment(razorpay_order_id, razorpay_payment_id, razorpay_signature):
        try:
            razorpay_client.utility.verify_payment_signature({
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature,
            })
            return True
        except:
            return False

    @staticmethod
    def process_refund(payment, amount=None):
        try:
            refund_amount = int((amount or payment.amount) * 100)
            refund = razorpay_client.payment.refund(
                payment.stripe_payment_intent_id,
                {'amount': refund_amount}
            )
            payment.status = 'REFUNDED'
            payment.save()
            return refund
        except Exception as e:
            raise ValueError(f'Refund failed: {str(e)}')