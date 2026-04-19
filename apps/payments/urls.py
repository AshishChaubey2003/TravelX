from django.urls import path
from .views import CreateCheckoutView, StripeWebhookView, PaymentSuccessView, PaymentCancelView

urlpatterns = [
    path('create-checkout/', CreateCheckoutView.as_view(), name='create-checkout'),
    path('webhook/', StripeWebhookView.as_view(), name='stripe-webhook'),
    path('success/', PaymentSuccessView.as_view(), name='payment-success'),
    path('cancel/', PaymentCancelView.as_view(), name='payment-cancel'),
]