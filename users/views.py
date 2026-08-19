import logging

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from .models import EmailVerificationToken, PasswordResetToken, User
from .serializers import (
    EmailSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    RegisterSerializer,
    ResetConfirmSerializer,
    TokenSerializer,
    UserSerializer,
    usable_token_or_error,
)
from .services import send_password_reset_email, send_verification_email

logger = logging.getLogger(__name__)


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        send_verification_email(user)
        return Response(
            {
                "message": "Account created. Check your email to verify it.",
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data)


class LogoutView(APIView):
    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response(
                {
                    "error": {
                        "code": "validation_error",
                        "message": "A refresh token is required.",
                        "details": {"refresh": ["This field is required."]},
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = usable_token_or_error(
            EmailVerificationToken, serializer.validated_data["token"]
        )
        token.user.is_email_verified = True
        token.user.save(update_fields=["is_email_verified"])
        token.consume()
        return Response({"message": "Email verified successfully."})


class ResendVerificationView(APIView):
    def post(self, request):
        if request.user.is_email_verified:
            return Response({"message": "Email is already verified."})
        send_verification_email(request.user)
        return Response({"message": "Verification email sent."})


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(
            email=serializer.validated_data["email"].lower()
        ).first()
        if user and user.is_active:
            try:
                send_password_reset_email(user)
            except Exception:
                logger.exception("Password reset email delivery failed")
        return Response(
            {"message": "If that account exists, a reset email has been sent."}
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        serializer = ResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = usable_token_or_error(
            PasswordResetToken, serializer.validated_data["token"]
        )
        token.user.set_password(serializer.validated_data["new_password"])
        token.user.save(update_fields=["password"])
        token.consume()
        self._blacklist_user_tokens(token.user)
        return Response({"message": "Password reset successfully."})

    @staticmethod
    def _blacklist_user_tokens(user):
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )

        for outstanding in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=outstanding)


class PasswordChangeView(APIView):
    @transaction.atomic
    def post(self, request):
        serializer = PasswordChangeSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        PasswordResetConfirmView._blacklist_user_tokens(request.user)
        return Response(
            {"message": "Password changed successfully. Please log in again."}
        )


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
