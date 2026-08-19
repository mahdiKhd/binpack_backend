from django.contrib.auth import authenticate, password_validation
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User


class StrictFieldsMixin:
    def to_internal_value(self, data):
        if hasattr(data, "keys"):
            unknown = set(data.keys()) - set(self.fields.keys())
            if unknown:
                raise serializers.ValidationError(
                    {key: ["Unknown field."] for key in sorted(unknown)}
                )
        return super().to_internal_value(data)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "is_email_verified",
            "date_joined",
        )
        read_only_fields = ("id", "email", "is_email_verified", "date_joined")


class RegisterSerializer(StrictFieldsMixin, serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)

    def validate_email(self, value):
        value = User.objects.normalize_email(value).lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "An account with this email already exists."
            )
        return value

    def validate_password(self, value):
        password_validation.validate_password(value)
        return value

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class LoginSerializer(StrictFieldsMixin, serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            email=attrs["email"].lower(),
            password=attrs["password"],
        )
        if not user or not user.is_active:
            raise serializers.ValidationError("Invalid email or password.")
        refresh = RefreshToken.for_user(user)
        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": UserSerializer(user).data,
        }


class TokenSerializer(StrictFieldsMixin, serializers.Serializer):
    token = serializers.CharField(trim_whitespace=False)


class EmailSerializer(StrictFieldsMixin, serializers.Serializer):
    email = serializers.EmailField()


class ResetConfirmSerializer(TokenSerializer):
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_new_password(self, value):
        password_validation.validate_password(value)
        return value


class PasswordChangeSerializer(StrictFieldsMixin, serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        password_validation.validate_password(value, self.context["request"].user)
        return value


def usable_token_or_error(model, raw_token):
    try:
        token = (
            model.objects.select_for_update()
            .select_related("user")
            .get(token_hash=model.digest(raw_token))
        )
    except model.DoesNotExist as exc:
        raise serializers.ValidationError(
            {"token": ["Invalid or expired token."]}
        ) from exc
    if token.used_at is not None or token.expires_at <= timezone.now():
        raise serializers.ValidationError({"token": ["Invalid or expired token."]})
    return token
