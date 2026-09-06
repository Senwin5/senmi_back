# senmi_ride/matching.py

import logging
import math
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from django.conf import settings
from django.utils import timezone

from .models import RideDriverAvailability

from senmi.utils import send_fcm_notification


logger = logging.getLogger(__name__)


# ============================================================
# RIDE MATCHING SETTINGS
# ============================================================

MATCHING_RADIUS_KM = getattr(
    settings,
    "RIDE_MATCHING_RADIUS_KM",
    15,
)

MAX_DRIVERS_TO_NOTIFY = getattr(
    settings,
    "RIDE_MAX_DRIVERS_TO_NOTIFY",
    10,
)

LOCATION_MAX_AGE_MINUTES = getattr(
    settings,
    "RIDE_DRIVER_LOCATION_MAX_AGE_MINUTES",
    10,
)


# ============================================================
# DISTANCE
# ============================================================

def calculate_distance_km(
    latitude1,
    longitude1,
    latitude2,
    longitude2,
):
    """
    Calculate straight-line distance between two
    latitude/longitude points using the Haversine formula.

    Returns:
        float: distance in kilometres
    """

    earth_radius_km = 6371.0

    lat1 = math.radians(float(latitude1))
    lat2 = math.radians(float(latitude2))

    delta_lat = math.radians(
        float(latitude2) - float(latitude1)
    )

    delta_lng = math.radians(
        float(longitude2) - float(longitude1)
    )

    a = (
        math.sin(delta_lat / 2) ** 2
        +
        math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lng / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )

    return earth_radius_km * c


# ============================================================
# FIND NEAREST DRIVERS
# ============================================================

def find_nearest_drivers(ride):
    """
    Find approved and online drivers near the ride pickup.

    Driver must:

        - be approved
        - be online
        - have RideDriverAvailability
        - have recent GPS location
        - be within matching radius

    Returns:

        [
            {
                "driver": RideDriverProfile,
                "distance_km": 1.23,
            }
        ]
    """

    # --------------------------------------------------------
    # RIDE MUST STILL BE PENDING
    # --------------------------------------------------------

    if ride.status != "pending":

        logger.info(
            "Ride %s is no longer pending. "
            "Driver matching skipped.",
            ride.ride_id,
        )

        return []


    # --------------------------------------------------------
    # GPS MUST BE RECENT
    # --------------------------------------------------------

    location_cutoff = (
        timezone.now()
        -
        timedelta(
            minutes=LOCATION_MAX_AGE_MINUTES
        )
    )


    # --------------------------------------------------------
    # APPROVED + ONLINE + RECENT GPS
    # --------------------------------------------------------

    availabilities = (
        RideDriverAvailability.objects
        .select_related(
            "driver",
            "driver__user",
        )
        .filter(
            driver__status="approved",
            driver__is_online=True,
            updated_at__gte=location_cutoff,
        )
    )


    nearest_drivers = []


    # --------------------------------------------------------
    # CALCULATE DRIVER DISTANCE FROM PICKUP
    # --------------------------------------------------------

    for availability in availabilities:

        try:

            distance_km = calculate_distance_km(

                ride.pickup_lat,
                ride.pickup_lng,

                availability.latitude,
                availability.longitude,

            )

        except (
            TypeError,
            ValueError,
        ):

            logger.warning(
                "Invalid GPS data for driver %s.",
                availability.driver.driver_id,
            )

            continue


        # ----------------------------------------------------
        # DRIVER MUST BE WITHIN MATCHING RADIUS
        # ----------------------------------------------------

        if distance_km > MATCHING_RADIUS_KM:

            continue


        nearest_drivers.append({

            "driver":
                availability.driver,

            "distance_km":
                round(distance_km, 2),

        })


    # --------------------------------------------------------
    # NEAREST FIRST
    # --------------------------------------------------------

    nearest_drivers.sort(
        key=lambda item: item["distance_km"]
    )


    # --------------------------------------------------------
    # ONLY NOTIFY TOP DRIVERS
    # --------------------------------------------------------

    return nearest_drivers[
        :MAX_DRIVERS_TO_NOTIFY
    ]


# ============================================================
# NOTIFY NEAREST DRIVERS
# ============================================================

def notify_nearest_drivers(ride):
    """
    Notify the nearest available drivers.

    Each driver receives:

        1. Firebase push notification
        2. Ride WebSocket notification

    IMPORTANT:

    This function DOES NOT assign the ride.

    The driver only becomes assigned when AcceptRideView
    successfully locks and accepts the RideRequest.
    """

    # --------------------------------------------------------
    # SAFETY
    # --------------------------------------------------------

    if ride.status != "pending":

        logger.info(
            "Ride %s is not pending. "
            "No driver notification sent.",
            ride.ride_id,
        )

        return []


    # --------------------------------------------------------
    # FIND DRIVERS
    # --------------------------------------------------------

    nearest_drivers = find_nearest_drivers(
        ride
    )


    # --------------------------------------------------------
    # NO DRIVERS
    # --------------------------------------------------------

    if not nearest_drivers:

        logger.info(
            "No nearby drivers found for ride %s.",
            ride.ride_id,
        )

        return []


    # --------------------------------------------------------
    # CHANNEL LAYER
    # --------------------------------------------------------

    channel_layer = get_channel_layer()


    notified_drivers = []


    # --------------------------------------------------------
    # SEND TO EACH DRIVER
    # --------------------------------------------------------

    for item in nearest_drivers:

        driver_profile = item["driver"]

        distance_to_pickup = item[
            "distance_km"
        ]

        driver_user = driver_profile.user


        # ====================================================
        # FCM PUSH NOTIFICATION
        #
        # Uses your existing working Senmi
        # send_fcm_notification() function.
        # ====================================================

        try:

            send_fcm_notification(

                user=driver_user,

                title="New Ride Request",

                body=(
                    f"New ride request "
                    f"{distance_to_pickup:.1f} km away."
                ),

                data={

                    "type":
                        "ride_request",

                    "ride_id":
                        ride.ride_id,

                    "pickup_address":
                        ride.pickup_address,

                    "destination_address":
                        ride.destination_address,

                    "fare":
                        ride.fare,

                    "distance_to_pickup_km":
                        distance_to_pickup,

                },

            )

        except Exception:

            logger.exception(
                "FCM ride notification failed "
                "for driver %s, ride %s.",
                driver_profile.driver_id,
                ride.ride_id,
            )


        # ====================================================
        # WEBSOCKET NOTIFICATION
        # ====================================================

        if channel_layer is not None:

            driver_group = (
                f"ride_driver_{driver_user.id}"
            )

            try:

                async_to_sync(
                    channel_layer.group_send
                )(
                    driver_group,

                    {
                        "type":
                            "ride_request",

                        "ride_id":
                            ride.ride_id,

                        "pickup_address":
                            ride.pickup_address,

                        "destination_address":
                            ride.destination_address,

                        "pickup_lat":
                            ride.pickup_lat,

                        "pickup_lng":
                            ride.pickup_lng,

                        "destination_lat":
                            ride.destination_lat,

                        "destination_lng":
                            ride.destination_lng,

                        "estimated_distance_km":
                            float(
                                ride.estimated_distance_km
                            ),

                        "estimated_duration_minutes":
                            ride.estimated_duration_minutes,

                        "fare":
                            float(ride.fare),

                        "distance_to_pickup_km":
                            distance_to_pickup,

                        "payment_method":
                            ride.payment_method,

                        "status":
                            ride.status,

                    },
                )


            except Exception:

                logger.exception(
                    "Ride WebSocket notification failed "
                    "for driver %s, ride %s.",
                    driver_profile.driver_id,
                    ride.ride_id,
                )


        # ====================================================
        # RECORD SUCCESSFUL MATCH ATTEMPT
        # ====================================================

        notified_drivers.append({

            "driver_id":
                driver_profile.driver_id,

            "user_id":
                driver_user.id,

            "distance_km":
                distance_to_pickup,

        })


        logger.info(

            "Ride %s notified driver %s "
            "(%.2f km away).",

            ride.ride_id,

            driver_profile.driver_id,

            distance_to_pickup,

        )


    # --------------------------------------------------------
    # FINAL LOG
    # --------------------------------------------------------

    logger.info(

        "Ride matching finished | "
        "ride=%s | "
        "drivers_notified=%s",

        ride.ride_id,

        len(notified_drivers),

    )


    return notified_drivers