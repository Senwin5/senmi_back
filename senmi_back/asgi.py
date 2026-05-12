import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

from senmi.routing import websocket_urlpatterns
from senmi.jwt_middleware import JwtAuthMiddleware

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'senmi_back.settings')

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,

    "websocket": JwtAuthMiddleware(
        URLRouter(
            websocket_urlpatterns
        )
    ),
})