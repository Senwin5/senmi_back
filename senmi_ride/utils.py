from decimal import Decimal, ROUND_HALF_UP
from math import radians, sin, cos, sqrt, atan2
import requests

from django.conf import settings

from .models import RidePricingConfig


# ============================================================
# DISTANCE
# ============================================================

def calculate_distance(
    pickup_lat,
    pickup_lng,
    destination_lat,
    destination_lng,
):
    """
    Calculate straight-line distance in kilometres.

    This is kept for existing/internal Ride calculations.
    """

    lat1 = radians(float(pickup_lat))
    lon1 = radians(float(pickup_lng))

    lat2 = radians(float(destination_lat))
    lon2 = radians(float(destination_lng))

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1)
        * cos(lat2)
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(
        sqrt(a),
        sqrt(1 - a)
    )

    earth_radius_km = 6371

    return Decimal(
        str(earth_radius_km * c)
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


# ============================================================
# RIDE ROAD ROUTE
# ============================================================

def calculate_road_route(
    pickup_lat,
    pickup_lng,
    destination_lat,
    destination_lng,
):
    """
    Calculate actual driving distance and estimated duration
    for a Ride using Google Routes API.

    This is Ride-only functionality.
    """

    # --------------------------------------------------------
    # SERVER GOOGLE MAPS API KEY
    # --------------------------------------------------------

    api_key = (
        getattr(
            settings,
            "GOOGLE_MAPS_SERVER_API_KEY",
            None,
        )
        or getattr(
            settings,
            "GOOGLE_MAPS_API_KEY",
            None,
        )
    )

    if not api_key:
        raise ValueError(
            "Google Maps API key is not configured."
        )

    # --------------------------------------------------------
    # GOOGLE ROUTES API
    # --------------------------------------------------------

    url = (
        "https://routes.googleapis.com/"
        "directions/v2:computeRoutes"
    )

    payload = {
        "origin": {
            "location": {
                "latLng": {
                    "latitude": float(pickup_lat),
                    "longitude": float(pickup_lng),
                }
            }
        },

        "destination": {
            "location": {
                "latLng": {
                    "latitude": float(destination_lat),
                    "longitude": float(destination_lng),
                }
            }
        },

        "travelMode": "DRIVE",

        "routingPreference": "TRAFFIC_AWARE",

        "computeAlternativeRoutes": False,

        "languageCode": "en",

        "units": "METRIC",
    }

    headers = {
        "Content-Type": "application/json",

        "X-Goog-Api-Key": api_key,

        # Only request what the Ride fare needs.
        "X-Goog-FieldMask": (
            "routes.distanceMeters,"
            "routes.duration"
        ),
    }

    # --------------------------------------------------------
    # REQUEST ROUTE
    # --------------------------------------------------------

    try:

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=15,
        )

        response.raise_for_status()

        route_data = response.json()

    except requests.RequestException as exc:

        raise ValueError(
            "Unable to calculate the driving route right now."
        ) from exc

    except ValueError as exc:

        raise ValueError(
            "Invalid route response."
        ) from exc

    # --------------------------------------------------------
    # ROUTES
    # --------------------------------------------------------

    routes = route_data.get(
        "routes",
        []
    )

    if not routes:

        raise ValueError(
            "No driving route was found for these locations."
        )

    route = routes[0]

    distance_meters = route.get(
        "distanceMeters"
    )

    duration_value = route.get(
        "duration"
    )

    if (
        distance_meters is None
        or duration_value is None
    ):

        raise ValueError(
            "Incomplete route information was returned."
        )

    # --------------------------------------------------------
    # DISTANCE
    # --------------------------------------------------------

    distance_km = (
        Decimal(
            str(distance_meters)
        )
        / Decimal("1000")
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    # --------------------------------------------------------
    # DURATION
    #
    # Google returns duration in seconds format.
    #
    # Example:
    # "600s"
    # "601.5s"
    # --------------------------------------------------------

    duration_string = str(
        duration_value
    ).strip()

    try:

        if duration_string.endswith("s"):

            duration_seconds = float(
                duration_string[:-1]
            )

        else:

            duration_seconds = float(
                duration_string
            )

    except (
        TypeError,
        ValueError,
    ) as exc:

        raise ValueError(
            "Invalid route duration was returned."
        ) from exc

    # --------------------------------------------------------
    # ROUND UP PARTIAL MINUTES
    # --------------------------------------------------------

    duration_minutes = (
        int(duration_seconds) + 59
    ) // 60

    return (
        distance_km,
        duration_minutes,
    )


# ============================================================
# ACTIVE RIDE PRICING
# ============================================================

def get_active_ride_pricing():

    pricing = (
        RidePricingConfig.objects
        .filter(is_active=True)
        .order_by("-updated_at")
        .first()
    )

    if not pricing:
        raise ValueError(
            "No active ride pricing configuration exists."
        )

    return pricing


# ============================================================
# RIDE FARE
# ============================================================

def calculate_ride_fare(
    distance_km,
    duration_minutes,
    service_type="basic",
):

    pricing = get_active_ride_pricing()

    distance = Decimal(
        str(distance_km)
    )

    duration = Decimal(
        str(duration_minutes)
    )

    # --------------------------------------------------------
    # GENERAL / BASIC FARE
    # --------------------------------------------------------

    fare = (
        pricing.base_fare
        + (distance * pricing.per_km_rate)
        + (duration * pricing.per_minute_rate)
    )

    # --------------------------------------------------------
    # PREMIUM
    #
    # Premium = Basic fare + Premium surcharge
    #
    # The default Premium surcharge is ₦400.
    # --------------------------------------------------------

    if service_type == "premium":

        fare += pricing.premium_surcharge

    fare = fare.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    # --------------------------------------------------------
    # SENMI SERVICE FEE
    #
    # Current setting:
    # 15% Senmi
    # 85% driver
    # --------------------------------------------------------

    service_fee = (
        fare
        * pricing.service_fee_percentage
        / Decimal("100")
    )

    service_fee = service_fee.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    # --------------------------------------------------------
    # DRIVER EARNING
    # --------------------------------------------------------

    driver_earning = (
        fare - service_fee
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    return (
        fare,
        service_fee,
        driver_earning,
    )


# ============================================================
# PAYSTACK SETTINGS
# ============================================================

PAYSTACK_BASE_URL = (
    "https://api.paystack.co"
)


def get_paystack_headers():

    secret_key = getattr(
        settings,
        "PAYSTACK_SECRET_KEY",
        None,
    )

    if not secret_key:
        raise ValueError(
            "PAYSTACK_SECRET_KEY is not configured."
        )

    return {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }


# ============================================================
# PAYSTACK CHANNEL
# ============================================================

def get_paystack_channel(payment_method):

    channels = {
        "card": ["card"],
        "bank": ["bank"],
        "bank_transfer": ["bank_transfer"],
        "ussd": ["ussd"],
    }

    return channels.get(
        payment_method,
        ["card"],
    )


# ============================================================
# INITIALIZE COMMISSION PAYMENT
# ============================================================

def initialize_ride_commission_payment(
    payment,
    email,
):

    amount_in_kobo = int(
        payment.amount * Decimal("100")
    )

    payload = {
        "email": email,
        "amount": str(amount_in_kobo),
        "reference": payment.reference,
        "channels": get_paystack_channel(
            payment.payment_method
        ),
        "currency": "NGN",
        "metadata": {
            "payment_type": "ride_commission",
            "ride_id": (
                payment.ride.ride_id
                if payment.ride
                else None
            ),
            "driver_id": payment.driver.id,
        },
    }

    callback_url = getattr(
        settings,
        "PAYMENT_CALLBACK_URL",
        None,
    )

    if callback_url:
        payload["callback_url"] = callback_url

    response = requests.post(
        f"{PAYSTACK_BASE_URL}/transaction/initialize",
        headers=get_paystack_headers(),
        json=payload,
        timeout=30,
    )

    try:
        response_data = response.json()
    except ValueError:
        response_data = {}

    if (
        response.status_code >= 400
        or not response_data.get("status")
    ):
        message = (
            response_data.get("message")
            or "Unable to initialize Paystack payment."
        )

        raise ValueError(message)

    data = response_data.get(
        "data",
        {}
    )

    return {
        "authorization_url": data.get(
            "authorization_url"
        ),
        "access_code": data.get(
            "access_code"
        ),
        "reference": data.get(
            "reference"
        ),
    }


# ============================================================
# VERIFY PAYSTACK TRANSACTION
# ============================================================

def verify_ride_commission_payment(
    reference
):

    response = requests.get(
        (
            f"{PAYSTACK_BASE_URL}"
            f"/transaction/verify/"
            f"{reference}"
        ),
        headers=get_paystack_headers(),
        timeout=30,
    )

    try:
        response_data = response.json()
    except ValueError:
        response_data = {}

    if (
        response.status_code >= 400
        or not response_data.get("status")
    ):
        return {
            "success": False,
            "message": (
                response_data.get("message")
                or "Unable to verify Paystack transaction."
            ),
            "data": {},
        }

    data = response_data.get(
        "data",
        {}
    )

    return {
        "success": (
            data.get("status") == "success"
        ),
        "message": response_data.get(
            "message"
        ),
        "data": data,
    }