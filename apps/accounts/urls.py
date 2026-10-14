from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework.throttling import ScopedRateThrottle

from .throttles import LoginAccountThrottle
from .views import RegisterView, VerifyOTPView, ResendOTPView


# F-001: subclass the stock simplejwt view to attach throttling without
# changing authentication behaviour. ScopedRateThrottle picks up `throttle_scope`
# as the IP-keyed rate ('login'); LoginAccountThrottle keys on the submitted
# username with its own rate ('login_account'). Both must pass for the view to
# accept the request.
class ThrottledTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [ScopedRateThrottle, LoginAccountThrottle]
    throttle_scope = 'login'
    login_account_scope = 'login_account'


urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),
    path('resend-otp/', ResendOTPView.as_view(), name='resend-otp'),
    path('token/', ThrottledTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]