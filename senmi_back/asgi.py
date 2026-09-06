# senmi_back/asgi.py

import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "senmi_back.settings"
)

from django.core.asgi import get_asgi_application

django_asgi_app = get_asgi_application()


from channels.routing import (
    ProtocolTypeRouter,
    URLRouter,
)


from senmi.jwt_middleware import (
    JwtAuthMiddleware
)


from senmi.routing import (
    websocket_urlpatterns as package_websocket_urlpatterns
)


from senmi_ride.routing import (
    websocket_urlpatterns as ride_websocket_urlpatterns
)


# ============================================================
# COMBINE PACKAGE + RIDE WEBSOCKET ROUTES
# ============================================================

websocket_urlpatterns = (

    package_websocket_urlpatterns

    +

    ride_websocket_urlpatterns

)


application = ProtocolTypeRouter({

    "http":
        django_asgi_app,

    "websocket":
        JwtAuthMiddleware(

            URLRouter(
                websocket_urlpatterns
            )

        ),

})