# senmi/permissions.py
from math import atan2, cos, radians, sin, sqrt
from rest_framework.permissions import BasePermission
from senmi_back import settings
from venv import logger



class IsAdminOrSupport(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role in ['admin', 'support']
        )
    


 
# ------------------------------
# Distance & price helpers
def calculate_distance(lat1, lng1, lat2, lng2):
    R = 6371.0  # Earth radius in km
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c  # distance in km


def calculate_price(distance_km):
    base_fee = settings.BASE_FEE
    per_km_rate = settings.PER_KM_RATE
    multiplier = settings.FUEL_MULTIPLIER
    return (base_fee + (distance_km * per_km_rate)) * multiplier


# senmi/permissions.py

"""from math import atan2, cos, radians, sin, sqrt
from django.utils import timezone
from django.conf import settings
from rest_framework.permissions import BasePermission


# ------------------------------
# Admin / Support Permission
# ------------------------------
class IsAdminOrSupport(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role in ['admin', 'support']
        )


# ------------------------------
# Distance helper
# ------------------------------
def calculate_distance(lat1, lng1, lat2, lng2):
    R = 6371.0  # Earth radius in km
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)

    a = (
        sin(dlat / 2) ** 2 +
        cos(radians(lat1)) *
        cos(radians(lat2)) *
        sin(dlng / 2) ** 2
    )

    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c  # distance in km


# ------------------------------
# Time-based pricing helper
# ------------------------------
def get_time_multiplier():
    hour = timezone.localtime().hour

    # Morning (cheap)
    if 6 <= hour < 11:
        return 1.0

    # Afternoon (normal)
    elif 11 <= hour < 15:
        return 1.2

    # Evening (peak)
    elif 15 <= hour < 22:
        return 1.5

    # Night
    else:
        return 1.1


# ------------------------------
# Price calculator (UPDATED)
# ------------------------------
def calculate_price(distance_km):
    base_fee = settings.BASE_FEE
    per_km_rate = settings.PER_KM_RATE

    fuel_multiplier = settings.FUEL_MULTIPLIER
    time_multiplier = get_time_multiplier()

    return (
        (base_fee + (distance_km * per_km_rate))
        * fuel_multiplier
        * time_multiplier
    )"""


