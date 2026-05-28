
from django.urls import re_path

from .consumers import (TrackingConsumer,AdminRidersConsumer,AdminDashboardConsumer,)

websocket_urlpatterns = [
    re_path(r'ws/tracking/(?P<package_id>[\w-]+)/$',TrackingConsumer.as_asgi()),
    re_path(r'ws/admin/riders/$',AdminRidersConsumer.as_asgi()),
    re_path(r'ws/admin-dashboard/$',AdminDashboardConsumer.as_asgi()),
]
