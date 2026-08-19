from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

from users.models import User


@database_sync_to_async
def user_for_token(raw_token):
    try:
        token = AccessToken(raw_token)
        return User.objects.get(id=token["user_id"], is_active=True)
    except (InvalidToken, TokenError, User.DoesNotExist, KeyError):
        return AnonymousUser()


class JWTAuthMiddleware:
    """Authenticate WebSockets with ws/notifications/?token=<access JWT>."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        query = parse_qs(scope.get("query_string", b"").decode("utf-8"))
        raw_token = query.get("token", [None])[0]
        scope["user"] = (
            await user_for_token(raw_token) if raw_token else AnonymousUser()
        )
        return await self.app(scope, receive, send)
