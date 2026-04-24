import os
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from channels.auth import AuthMiddlewareStack
import senmi.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'senmi_back.settings')

application = ProtocolTypeRouter({
    "http": get_asgi_application(),

    "websocket": AuthMiddlewareStack(
        URLRouter(
            senmi.routing.websocket_urlpatterns
        )
    ),
})