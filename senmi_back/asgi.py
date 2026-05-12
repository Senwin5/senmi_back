from urllib.parse import parse_qs

from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

User = get_user_model()


@database_sync_to_async
def get_user(token):

    try:
        # 🔥 IMPORT INSIDE FUNCTION (prevents Django startup crash)
        from rest_framework_simplejwt.tokens import AccessToken

        access_token = AccessToken(token)

        user_id = access_token.get("user_id")

        if not user_id:
            return AnonymousUser()

        return User.objects.get(id=user_id)

    except Exception as e:
        print("JWT ERROR:", e)
        return AnonymousUser()


class JwtAuthMiddleware(BaseMiddleware):

    async def __call__(self, scope, receive, send):

        try:
            query_string = parse_qs(
                scope["query_string"].decode()
            )

            token_list = query_string.get("token")

            if token_list:
                token = token_list[0]
                scope["user"] = await get_user(token)
            else:
                scope["user"] = AnonymousUser()

        except Exception as e:
            print("MIDDLEWARE ERROR:", e)
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)