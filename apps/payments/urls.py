from django.urls import path
from .views import (
    CreateRazorpayOrderView,
    VerifyRazorpayPaymentView,
    RefundView,
    PaymentSuccessView,
    PaymentCancelView,
)
from .webhooks import RazorpayWebhookView

urlpatterns = [
    path('razorpay/create-order/', CreateRazorpayOrderView.as_view()),
    path('razorpay/verify/', VerifyRazorpayPaymentView.as_view()),
    path('razorpay/webhook/', RazorpayWebhookView.as_view()),
    path('refund/', RefundView.as_view()),
    path('success/', PaymentSuccessView.as_view()),
    path('cancel/', PaymentCancelView.as_view()),
]