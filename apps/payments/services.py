import hashlib
import hmac
import logging

import razorpay
from django.conf import settings
from django.db import transaction
from .models import Payment
from apps.bookings.models import Booking

# Resolved at import time rather than inside the except clause: if a future
# SDK layout moved this name, `except razorpay.errors.X` would raise
# AttributeError while handling the original error. The generic handler below
# still fails closed either way.
try:
    from razorpay.errors import SignatureVerificationError
except ImportError:  # pragma: no cover - SDK layout differs
    class SignatureVerificationError(Exception):
        """Fallback when the SDK does not expose this error type."""

logger = logging.getLogger(__name__)


class PaymentNotPayableError(ValueError):
    """A (new) payment order cannot be issued for this booking in its current state."""


def _order_from_payment(payment):
    """
    Rebuild the order dict callers need (id / amount / currency) from the stored
    payment, so a repeat request is answered without another gateway call.
    """
    return {
        'id': payment.stripe_session_id,
        'amount': int(payment.amount * 100),
        'currency': 'INR',
    }

razorpay_client = razorpay.Client(
    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
)


class RazorpayService:

    @staticmethod
    def create_order(booking):
        """
        Return the canonical Razorpay order for this booking's payment attempt.

        Payment.stripe_session_id (a legacy name: it holds the Razorpay ORDER id)
        is canonical; Booking.stripe_session_id is only a mirror and is kept equal
        to it. A repeat call reuses the stored order instead of creating a second
        one, and never issues an order for a payment that is already captured,
        failed or refunded.
        """
        reusable = RazorpayService._existing_order(booking)
        if reusable is not None:
            return reusable

        amount = int(booking.total_amount * 100)

        # Gateway call is made OUTSIDE any row lock; the state is re-checked
        # under the lock below, so a concurrent winner is never overwritten.
        order = razorpay_client.order.create({
            'amount': amount,
            'currency': 'INR',
            'receipt': str(booking.id)[:40],
            'notes': {
                'booking_id': str(booking.id),
                'user_email': booking.user.email,
            }
        })

        with transaction.atomic():
            locked = Booking.objects.select_for_update().get(pk=booking.pk)
            payment = Payment.objects.select_for_update().filter(booking=locked).first()
            RazorpayService._assert_payable(locked, payment)

            if payment is not None and payment.stripe_session_id:
                # Another request recorded an order while we were calling the
                # gateway. Keep that one; the unpaid duplicate is simply unused.
                logger.warning(
                    'create_order lost a race for booking %s; keeping the recorded order',
                    locked.pk,
                )
                RazorpayService._mirror_order_on_booking(locked, payment.stripe_session_id)
                result = _order_from_payment(payment)
            else:
                if payment is None:
                    Payment.objects.create(
                        booking=locked,
                        amount=locked.total_amount,
                        currency='inr',
                        status='PENDING',
                        stripe_session_id=order['id'],
                    )
                else:
                    payment.stripe_session_id = order['id']
                    payment.amount = locked.total_amount
                    payment.save(update_fields=['stripe_session_id', 'amount'])
                RazorpayService._mirror_order_on_booking(locked, order['id'])
                result = order

        booking.stripe_session_id = result['id']
        return result

    @staticmethod
    def _assert_payable(booking, payment):
        if booking.status != 'PENDING':
            raise PaymentNotPayableError('This booking can no longer be paid for.')
        if payment is not None and payment.status != 'PENDING':
            if payment.status == 'SUCCESS':
                raise PaymentNotPayableError(
                    'A payment has already been recorded for this booking.')
            raise PaymentNotPayableError(
                'A new payment order cannot be created for this booking.')

    @staticmethod
    def _mirror_order_on_booking(booking, order_id):
        if booking.stripe_session_id != order_id:
            booking.stripe_session_id = order_id
            booking.save(update_fields=['stripe_session_id'])

    @staticmethod
    def _existing_order(booking):
        """The stored order for a still-PENDING payment, or None if one must be made."""
        with transaction.atomic():
            locked = Booking.objects.select_for_update().get(pk=booking.pk)
            payment = Payment.objects.select_for_update().filter(booking=locked).first()
            RazorpayService._assert_payable(locked, payment)
            if payment is None or not payment.stripe_session_id:
                return None
            if payment.amount != locked.total_amount:
                raise PaymentNotPayableError(
                    'The payment order no longer matches the booking amount.')
            RazorpayService._mirror_order_on_booking(locked, payment.stripe_session_id)
            result = _order_from_payment(payment)
        booking.stripe_session_id = result['id']
        return result

    @staticmethod
    def verify_payment(razorpay_order_id, razorpay_payment_id, razorpay_signature):
        try:
            razorpay_client.utility.verify_payment_signature({
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature,
            })
            return True
        except SignatureVerificationError:
            # Expected outcome for a bad signature: quiet, fails closed.
            return False
        except Exception as exc:
            # The previous bare `except:` also swallowed KeyboardInterrupt and
            # SystemExit, and reported genuine bugs as "invalid signature".
            # Still fails closed, but the cause is now visible.
            logger.error(
                'Payment-signature verification errored: %s', type(exc).__name__
            )
            return False

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
        """
        Verify an inbound Razorpay webhook.

        HMAC-SHA256 over the EXACT raw request body, keyed with the dedicated
        webhook secret (NOT the API key secret), compared in constant time.
        Fails closed when either the secret or the signature is missing, so an
        unconfigured deployment rejects every webhook rather than trusting it.
        """
        secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', '')
        if not secret or not signature:
            return False
        expected = hmac.new(
            secret.encode('utf-8'), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def initiate_refund(payment, amount=None):
        """
        Ask Razorpay for a refund and return the refund dict.

        Deliberately does NOT mark the payment REFUNDED. A refund request is an
        initiation, not a completion; only the refund.processed webhook confirms
        it. The caller records REFUND_PENDING plus the returned refund id.

        Raises ValueError with a generic message on gateway failure; the real
        cause is logged server-side and never returned to the client.
        """
        refund_amount = int((amount or payment.amount) * 100)
        try:
            return razorpay_client.payment.refund(
                payment.stripe_payment_intent_id,
                {'amount': refund_amount},
            )
        except Exception as exc:
            logger.error(
                'Razorpay refund call failed for payment %s: %s',
                payment.pk, type(exc).__name__,
            )
            raise ValueError('Refund could not be initiated')

    @staticmethod
    def process_refund(payment, amount=None):
        """
        DEPRECATED - conflates refund initiation with refund completion by
        marking the payment REFUNDED before Razorpay has confirmed anything.

        Kept unchanged ONLY so this change stays non-breaking: RefundView still
        calls it. It is removed in the same change that rewrites RefundView to
        use initiate_refund(). Do not add new callers.
        """
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