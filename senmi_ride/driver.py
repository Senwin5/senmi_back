# senmi_ride/driver.py

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from .models import (
    RideDriverProfile,
    RideDriverAvailability,
    RideRequest,
)

from .serializers import (
    RideDriverAvailabilitySerializer,
)


# ============================================================
# DRIVER ONLINE / OFFLINE
# ============================================================

class DriverOnlineStatusView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request):

        profile = get_object_or_404(
            RideDriverProfile,
            user=request.user,
        )

        if profile.status != "approved":

            return Response(
                {
                    "detail":
                        "Your driver account must be "
                        "approved before going online."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        is_online = request.data.get(
            "is_online"
        )

        if not isinstance(
            is_online,
            bool
        ):

            return Response(
                {
                    "detail":
                        "is_online must be true or false."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ----------------------------------------------------
        # GO OFFLINE
        # ----------------------------------------------------

        if not is_online:

            profile.is_online = False

            profile.save(
                update_fields=[
                    "is_online",
                ]
            )

            RideDriverAvailability.objects.filter(
                driver=profile
            ).delete()

            return Response(
                {
                    "driver_id":
                        profile.driver_id,

                    "is_online":
                        False,

                    "status":
                        profile.status,

                    "message":
                        "You are now offline.",
                },
                status=status.HTTP_200_OK
            )

        # ----------------------------------------------------
        # GO ONLINE
        # ----------------------------------------------------

        profile.is_online = True

        profile.save(
            update_fields=[
                "is_online",
            ]
        )

        return Response(
            {
                "driver_id":
                    profile.driver_id,

                "is_online":
                    True,

                "status":
                    profile.status,

                "message":
                    "You are now online.",
            },
            status=status.HTTP_200_OK
        )


# ============================================================
# DRIVER AVAILABILITY LOCATION
# ============================================================

class DriverAvailabilityLocationView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request):

        profile = get_object_or_404(
            RideDriverProfile,
            user=request.user,
        )

        if profile.status != "approved":

            return Response(
                {
                    "detail":
                        "Driver is not approved."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        if not profile.is_online:

            return Response(
                {
                    "detail":
                        "Driver must be online."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        latitude = request.data.get(
            "latitude"
        )

        longitude = request.data.get(
            "longitude"
        )

        if latitude is None or longitude is None:

            return Response(
                {
                    "detail":
                        "latitude and longitude "
                        "are required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:

            latitude = float(latitude)
            longitude = float(longitude)

        except (
            TypeError,
            ValueError,
        ):

            return Response(
                {
                    "detail":
                        "Invalid latitude or longitude."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if not -90 <= latitude <= 90:

            return Response(
                {
                    "detail":
                        "Invalid latitude."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if not -180 <= longitude <= 180:

            return Response(
                {
                    "detail":
                        "Invalid longitude."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        availability, created = (
            RideDriverAvailability.objects.update_or_create(
                driver=profile,
                defaults={
                    "latitude": latitude,
                    "longitude": longitude,
                },
            )
        )

        return Response(
            RideDriverAvailabilitySerializer(
                availability
            ).data,
            status=status.HTTP_200_OK
        )


# ============================================================
# DRIVER CANCEL RIDE
# ============================================================

class DriverCancelRideView(APIView):

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, ride_id):

        ride = get_object_or_404(
            RideRequest.objects.select_for_update(),
            ride_id=ride_id,
        )

        # ----------------------------------------------------
        # DRIVER MUST BE ASSIGNED
        # ----------------------------------------------------

        if ride.driver_id != request.user.id:

            return Response(
                {
                    "detail":
                        "You are not the driver "
                        "for this ride."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # ----------------------------------------------------
        # COMPLETED / ALREADY CANCELLED
        # ----------------------------------------------------

        if ride.status in [
            "completed",
            "cancelled",
        ]:

            return Response(
                {
                    "detail":
                        "This ride cannot be cancelled."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ----------------------------------------------------
        # ACCEPTED / ARRIVED / STARTED
        # ----------------------------------------------------

        ride.status = "cancelled"

        ride.cancelled_at = timezone.now()

        ride.save(
            update_fields=[
                "status",
                "cancelled_at",
                "updated_at",
            ]
        )

        return Response(
            {
                "message":
                    "Ride cancelled successfully.",

                "ride_id":
                    ride.ride_id,

                "status":
                    ride.status,
            },
            status=status.HTTP_200_OK
        )