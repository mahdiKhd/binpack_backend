from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RegisterView,
    ResendVerificationView,
    VerifyEmailView,
)

urlpatterns = [
    path("register", RegisterView.as_view(), name="register"),
    path("login", LoginView.as_view(), name="login"),
    path("logout", LogoutView.as_view(), name="logout"),
    path("token/refresh", TokenRefreshView.as_view(), name="token-refresh"),
    path("verify-email", VerifyEmailView.as_view(), name="verify-email"),
    path(
        "resend-verification",
        ResendVerificationView.as_view(),
        name="resend-verification",
    ),
    path("password/reset", PasswordResetRequestView.as_view(), name="password-reset"),
    path(
        "password/reset/confirm",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("password/change", PasswordChangeView.as_view(), name="password-change"),
    path("me", MeView.as_view(), name="me"),
]
