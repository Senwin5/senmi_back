# senmi_ride/consumers.py

import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from django.utils import timezone

from .models import (
    RideDriverAvailability,
    RideDriverProfile,
    RideRequest,
    RideTracking,
)


# ============================================================
# RIDE TRACKING CONSUMER
# Driver GPS is handled by DriverLocationConsumer below.
# ============================================================

class RideTrackingConsumer(
    AsyncWebsocketConsumer
):

    async def connect(self):

        user = self.scope.get("user")

        # ----------------------------------------------------
        # REQUIRE LOGIN
        # ----------------------------------------------------

        if not user or user.is_anonymous:

            await self.close(
                code=4001
            )

            return

        self.ride_id = (
            self.scope["url_route"]["kwargs"]["ride_id"]
        )

        # ----------------------------------------------------
        # VERIFY USER BELONGS TO THIS RIDE
        # ----------------------------------------------------

        ride = await self.get_authorized_ride(
            self.ride_id,
            user.id,
        )

        if not ride:

            await self.close(
                code=4003
            )

            return

        self.room_group_name = (
            f"ride_tracking_{self.ride_id}"
        )

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )

        await self.accept()

        # ----------------------------------------------------
        # SEND CURRENT RIDE STATUS
        # ----------------------------------------------------

        await self.send(
            text_data=json.dumps({

                "type":
                    "ride_status",

                "ride_id":
                    ride.ride_id,

                "status":
                    ride.status,

            })
        )

        # ----------------------------------------------------
        # SEND LATEST DRIVER LOCATION
        # ----------------------------------------------------

        latest_tracking = (
            await self.get_latest_tracking(
                self.ride_id
            )
        )

        if latest_tracking:

            await self.send(
                text_data=json.dumps({

                    "type":
                        "driver_location",

                    "ride_id":
                        self.ride_id,

                    "driver_id":
                        latest_tracking[
                            "driver_id"
                        ],

                    "lat":
                        latest_tracking[
                            "latitude"
                        ],

                    "lng":
                        latest_tracking[
                            "longitude"
                        ],

                    "timestamp":
                        latest_tracking[
                            "timestamp"
                        ],

                })
            )


    async def disconnect(
        self,
        close_code,
    ):

        if hasattr(
            self,
            "room_group_name"
        ):

            await self.channel_layer.group_discard(

                self.room_group_name,

                self.channel_name,

            )


    async def receive(
        self,
        text_data,
    ):

        # ----------------------------------------------------
        # PASSENGER TRACKING SOCKET IS RECEIVE-ONLY
        # ----------------------------------------------------

        await self.send(
            text_data=json.dumps({

                "type":
                    "error",

                "message":
                    "This connection does not "
                    "accept location updates.",

            })
        )


    # ========================================================
    # DRIVER LOCATION EVENT
    # ========================================================

    async def driver_location(
        self,
        event,
    ):

        await self.send(
            text_data=json.dumps({

                "type":
                    "driver_location",

                "ride_id":
                    event.get("ride_id"),

                "driver_id":
                    event.get("driver_id"),

                "lat":
                    event.get("lat"),

                "lng":
                    event.get("lng"),

                "status":
                    event.get("status"),

                "eta_minutes":
                    event.get("eta_minutes"),

                "timestamp":
                    event.get("timestamp"),

            })
        )


    # ========================================================
    # RIDE STATUS EVENT
    # ========================================================

    async def ride_status(
        self,
        event,
    ):

        await self.send(
            text_data=json.dumps({

                "type":
                    "ride_status",

                "ride_id":
                    event.get("ride_id"),

                "status":
                    event.get("status"),

            })
        )


    # ========================================================
    # DATABASE HELPERS
    # ========================================================

    @database_sync_to_async
    def get_authorized_ride(
        self,
        ride_id,
        user_id,
    ):

        try:

            ride = (
                RideRequest.objects
                .select_related(
                    "passenger",
                    "driver",
                )
                .get(
                    ride_id=ride_id
                )
            )

        except RideRequest.DoesNotExist:

            return None


        # Passenger is allowed.

        if ride.passenger_id == user_id:

            return ride


        # Assigned driver is allowed.

        if ride.driver_id == user_id:

            return ride


        return None


    @database_sync_to_async
    def get_latest_tracking(
        self,
        ride_id,
    ):

        tracking = (
            RideTracking.objects
            .filter(
                ride__ride_id=ride_id
            )
            .order_by(
                "-timestamp"
            )
            .first()
        )

        if not tracking:

            return None

        return {

            "driver_id":
                tracking.driver_id,

            "latitude":
                tracking.latitude,

            "longitude":
                tracking.longitude,

            "timestamp":
                tracking.timestamp.isoformat(),

        }


# ============================================================
# DRIVER LIVE LOCATION CONSUMER
#
# URL:
#
# /ws/ride-driver/<ride_id>/
#
# ONLY THE ASSIGNED DRIVER MAY SEND GPS.
#
# Driver:
#     GPS
#      ↓
#     Django
#      ↓
#     RideTracking
#      ↓
#     Passenger WebSocket
# ============================================================

class DriverLocationConsumer(
    AsyncWebsocketConsumer
):

    async def connect(self):

        user = self.scope.get("user")

        # ----------------------------------------------------
        # REQUIRE LOGIN
        # ----------------------------------------------------

        if not user or user.is_anonymous:

            await self.close(
                code=4001
            )

            return

        self.user_id = user.id

        self.ride_id = (
            self.scope["url_route"]["kwargs"]["ride_id"]
        )

        # ----------------------------------------------------
        # VERIFY ASSIGNED DRIVER
        # ----------------------------------------------------

        ride = await self.get_driver_ride(
            self.ride_id,
            self.user_id,
        )

        if not ride:

            await self.close(
                code=4003
            )

            return

        self.room_group_name = (
            f"ride_tracking_{self.ride_id}"
        )

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )

        await self.accept()


    async def disconnect(
        self,
        close_code,
    ):

        if hasattr(
            self,
            "room_group_name"
        ):

            await self.channel_layer.group_discard(

                self.room_group_name,

                self.channel_name,

            )


    async def receive(
        self,
        text_data,
    ):

        try:

            data = json.loads(
                text_data
            )

        except (
            json.JSONDecodeError,
            TypeError,
        ):

            await self.send(
                text_data=json.dumps({

                    "type":
                        "error",

                    "message":
                        "Invalid JSON data.",

                })
            )

            return


        latitude = data.get(
            "lat"
        )

        longitude = data.get(
            "lng"
        )


        if latitude is None:

            await self.send(
                text_data=json.dumps({

                    "type":
                        "error",

                    "message":
                        "Latitude is required.",

                })
            )

            return


        if longitude is None:

            await self.send(
                text_data=json.dumps({

                    "type":
                        "error",

                    "message":
                        "Longitude is required.",

                })
            )

            return


        # ----------------------------------------------------
        # CONVERT GPS
        # ----------------------------------------------------

        try:

            latitude = float(
                latitude
            )

            longitude = float(
                longitude
            )

        except (
            TypeError,
            ValueError,
        ):

            await self.send(
                text_data=json.dumps({

                    "type":
                        "error",

                    "message":
                        "Latitude and longitude "
                        "must be numbers.",

                })
            )

            return


        # ----------------------------------------------------
        # VALIDATE GPS RANGE
        # ----------------------------------------------------

        if not -90 <= latitude <= 90:

            await self.send(
                text_data=json.dumps({

                    "type":
                        "error",

                    "message":
                        "Invalid latitude.",

                })
            )

            return


        if not -180 <= longitude <= 180:

            await self.send(
                text_data=json.dumps({

                    "type":
                        "error",

                    "message":
                        "Invalid longitude.",

                })
            )

            return


        # ----------------------------------------------------
        # SAVE LOCATION
        # ----------------------------------------------------

        result = await self.save_driver_location(

            self.ride_id,

            self.user_id,

            latitude,

            longitude,

        )


        if not result:

            await self.send(
                text_data=json.dumps({

                    "type":
                        "error",

                    "message":
                        "Unable to update driver "
                        "location.",

                })
            )

            return


        # ----------------------------------------------------
        # BROADCAST TO PASSENGER
        # ----------------------------------------------------

        await self.channel_layer.group_send(

            self.room_group_name,

            {

                "type":
                    "driver_location",

                "ride_id":
                    self.ride_id,

                "driver_id":
                    self.user_id,

                "lat":
                    latitude,

                "lng":
                    longitude,

                "status":
                    result["status"],

                "timestamp":
                    result["timestamp"],

            },
        )


    # ========================================================
    # DATABASE
    # ========================================================

    @database_sync_to_async
    def get_driver_ride(
        self,
        ride_id,
        user_id,
    ):

        try:

            ride = RideRequest.objects.get(
                ride_id=ride_id
            )

        except RideRequest.DoesNotExist:

            return None


        if ride.driver_id != user_id:

            return None


        if ride.status not in [
            "accepted",
            "arrived",
            "started",
        ]:

            return None


        return ride


    @database_sync_to_async
    def save_driver_location(
        self,
        ride_id,
        user_id,
        latitude,
        longitude,
    ):

        try:

            ride = RideRequest.objects.get(
                ride_id=ride_id
            )

        except RideRequest.DoesNotExist:

            return None


        # ----------------------------------------------------
        # DRIVER MUST STILL BE ASSIGNED
        # ----------------------------------------------------

        if ride.driver_id != user_id:

            return None


        # ----------------------------------------------------
        # ONLY ACTIVE RIDE
        # ----------------------------------------------------

        if ride.status not in [
            "accepted",
            "arrived",
            "started",
        ]:

            return None


        # ----------------------------------------------------
        # SAVE RIDE TRACKING
        # ----------------------------------------------------

        RideTracking.objects.create(

            ride=ride,

            driver_id=user_id,

            latitude=latitude,

            longitude=longitude,

        )


        # ----------------------------------------------------
        # UPDATE DRIVER AVAILABILITY
        #
        # The same latest location is useful for future
        # matching when the driver remains online.
        # ----------------------------------------------------

        try:

            profile = (
                RideDriverProfile.objects.get(
                    user_id=user_id
                )
            )

        except RideDriverProfile.DoesNotExist:

            profile = None


        if profile:

            RideDriverAvailability.objects.update_or_create(

                driver=profile,

                defaults={

                    "latitude":
                        latitude,

                    "longitude":
                        longitude,

                },

            )


        return {

            "status":
                ride.status,

            "timestamp":
                timezone.now().isoformat(),

        }


# ============================================================
# DRIVER RIDE REQUEST CONSUMER
#
# URL:
#
# /ws/ride-driver-requests/
#
# Receives new nearby ride requests.
# ============================================================

class DriverRideRequestConsumer(
    AsyncWebsocketConsumer
):

    async def connect(self):

        user = self.scope.get("user")

        # ----------------------------------------------------
        # REQUIRE LOGIN
        # ----------------------------------------------------

        if not user or user.is_anonymous:

            await self.close(
                code=4001
            )

            return


        # ----------------------------------------------------
        # DRIVER MUST BE APPROVED
        # ----------------------------------------------------

        approved = (
            await self.is_approved_driver(
                user.id
            )
        )

        if not approved:

            await self.close(
                code=4003
            )

            return


        self.driver_user_id = user.id

        self.room_group_name = (
            f"ride_driver_{self.driver_user_id}"
        )

        await self.channel_layer.group_add(

            self.room_group_name,

            self.channel_name,

        )

        await self.accept()


    async def disconnect(
        self,
        close_code,
    ):

        if hasattr(
            self,
            "room_group_name"
        ):

            await self.channel_layer.group_discard(

                self.room_group_name,

                self.channel_name,

            )


    # ========================================================
    # NEW RIDE REQUEST
    # ========================================================

    async def ride_request(
        self,
        event,
    ):

        await self.send(

            text_data=json.dumps({

                "type":
                    "ride_request",

                "ride_id":
                    event.get(
                        "ride_id"
                    ),

                "pickup_address":
                    event.get(
                        "pickup_address"
                    ),

                "destination_address":
                    event.get(
                        "destination_address"
                    ),

                "pickup_lat":
                    event.get(
                        "pickup_lat"
                    ),

                "pickup_lng":
                    event.get(
                        "pickup_lng"
                    ),

                "destination_lat":
                    event.get(
                        "destination_lat"
                    ),

                "destination_lng":
                    event.get(
                        "destination_lng"
                    ),

                "estimated_distance_km":
                    event.get(
                        "estimated_distance_km"
                    ),

                "estimated_duration_minutes":
                    event.get(
                        "estimated_duration_minutes"
                    ),

                "fare":
                    event.get(
                        "fare"
                    ),

                "distance_to_pickup_km":
                    event.get(
                        "distance_to_pickup_km"
                    ),

                "payment_method":
                    event.get(
                        "payment_method"
                    ),

                "status":
                    event.get(
                        "status"
                    ),

            })
        )


    @database_sync_to_async
    def is_approved_driver(
        self,
        user_id,
    ):

        return (
            RideDriverProfile.objects
            .filter(
                user_id=user_id,
                status="approved",
            )
            .exists()
        )



