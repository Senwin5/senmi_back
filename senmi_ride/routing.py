from django.urls import re_path

from .consumers import (
    RideTrackingConsumer,
    DriverLocationConsumer,
    DriverRideRequestConsumer,
)


websocket_urlpatterns = [

    # ========================================================
    # PASSENGER RIDE TRACKING
    # ========================================================

    re_path(
        r"ws/ride/(?P<ride_id>[\w-]+)/$",
        RideTrackingConsumer.as_asgi(),
    ),

    # ========================================================
    # DRIVER LIVE GPS
    # ========================================================

    re_path(
        r"ws/ride-driver/(?P<ride_id>[\w-]+)/$",
        DriverLocationConsumer.as_asgi(),
    ),

    # ========================================================
    # DRIVER NEW RIDE REQUESTS
    # ========================================================

    re_path(
        r"ws/ride-driver-requests/$",
        DriverRideRequestConsumer.as_asgi(),
    ),
]