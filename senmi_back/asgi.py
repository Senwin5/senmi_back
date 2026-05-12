import os

# 🔥 MUST BE FIRST LINE
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "senmi_back.settings"
)

from django.core.asgi import get_asgi_application

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from senmi.routing import websocket_urlpatterns


# IMPORTANT: import AFTER Django setup
from senmi.jwt_middleware import JwtAuthMiddleware


application = ProtocolTypeRouter({

    "http": django_asgi_app,

    "websocket": JwtAuthMiddleware(
        URLRouter(websocket_urlpatterns)
    ),
})