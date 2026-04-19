import stripe
from django.conf import settings
from .models import Payment
from apps.bookings.models import Booking

stripe.api_key = settings.STRIPE_SECRET_KEY


class StripeService:

    @staticmethod
    def create_checkout_session(booking):
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'inr',
                    'product_data': {
                        'name': f'TravelX Booking #{str(booking.id)[:8]}',
                    },
                    'unit_amount': int(booking.total_amount * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='http://localhost:8000/api/v1/payments/success/?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='http://localhost:8000/api/v1/payments/cancel/',
            metadata={
                'booking_id': str(booking.id),
            }
        )

        # Payment record banao
        Payment.objects.create(
            booking=booking,
            stripe_session_id=session.id,
            amount=booking.total_amount,
            currency='inr',
            status='PENDING',
        )

        # Booking mein session id save karo
        booking.stripe_session_id = session.id
        booking.save()

        return session

    @staticmethod
    def handle_webhook(payload, sig_header):
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            raise ValueError("Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise ValueError("Invalid signature")

        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            booking_id = session['metadata']['booking_id']

            try:
                booking = Booking.objects.get(id=booking_id)
                booking.status = 'PAID'
                booking.save()

                payment = Payment.objects.get(stripe_session_id=session['id'])
                payment.status = 'SUCCESS'
                payment.stripe_payment_intent_id = session.get('payment_intent')
                payment.save()

            except Booking.DoesNotExist:
                pass

        return event