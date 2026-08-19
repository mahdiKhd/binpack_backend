from django.conf import settings
from django.core.mail import send_mail

from .models import EmailVerificationToken, PasswordResetToken


def send_verification_email(user):
    raw_token = EmailVerificationToken.issue_for(user)
    link = f"{settings.FRONTEND_URL}/verify-email?token={raw_token}"
    send_mail(
        "Verify your 3D Bin Packing account",
        f"Verify your email by opening this link:\n\n{link}\n\nThe link expires in 24 hours.",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )


def send_password_reset_email(user):
    raw_token = PasswordResetToken.issue_for(user)
    link = f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"
    send_mail(
        "Reset your 3D Bin Packing password",
        f"Reset your password by opening this link:\n\n{link}\n\nThe link expires in 1 hour.",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )
