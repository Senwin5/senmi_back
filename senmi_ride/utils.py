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

    This is currently used as a basic calculation.
    Later, your actual routing provider can replace this
    with road distance.
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
):

    pricing = get_active_ride_pricing()

    distance = Decimal(
        str(distance_km)
    )

    duration = Decimal(
        str(duration_minutes)
    )

    fare = (
        pricing.base_fare
        + (distance * pricing.per_km_rate)
        + (duration * pricing.per_minute_rate)
    )

    fare = fare.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    service_fee = (
        fare
        * pricing.service_fee_percentage
        / Decimal("100")
    )

    service_fee = service_fee.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

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