#jwt_middleware.py
from urllib.parse import parse_qs
from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

User = get_user_model()


@database_sync_to_async
def get_user(token):
    try:
        access_token = AccessToken(token)
        user_id = access_token["user_id"]
        return User.objects.get(id=user_id)
    except Exception as e:
        print("JWT ERROR:", e)
        return None


class JwtAuthMiddleware:

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):

        scope["user"] = AnonymousUser()

        query_string = parse_qs(scope["query_string"].decode())
        token = query_string.get("token")

        print("TOKEN RECEIVED:", token)

        if token:
            user = await get_user(token[0])
            if user:
                scope["user"] = user

        return await self.app(scope, receive, send)