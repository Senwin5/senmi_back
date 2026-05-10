from django.urls import re_path
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

from .consumers import TrackingConsumer, NotificationConsumer

websocket_urlpatterns = [
    re_path(r'ws/tracking/(?P<package_id>[\w-]+)/$', TrackingConsumer.as_asgi()),
    re_path(r'ws/notifications/$', NotificationConsumer.as_asgi()),
]