from django.urls import re_path
from .consumers import TrackingConsumer

websocket_urlpatterns = [
    re_path(r'ws/tracking/(?P<package_id>[\w-]+)/$', TrackingConsumer.as_asgi()),
]