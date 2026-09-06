# senmi_ride/customer.py

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from senmi_ride.matching import notify_nearest_drivers

from .models import RideRequest
from .serializers import RideRequestSerializer
from .utils import calculate_ride_fare


# ============================================================
#customer.py CREATE RIDE
# ============================================================

class CreateRideView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request):

        serializer = RideRequestSerializer(
            data=request.data
        )

        if not serializer.is_valid():

            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

        validated_data = serializer.validated_data

        distance = validated_data.get(
            "estimated_distance_km"
        )

        duration = validated_data.get(
            "estimated_duration_minutes"
        )

        try:

            (
                fare,
                service_fee,
                driver_earning,
            ) = calculate_ride_fare(
                distance,
                duration,
            )

        except ValueError as exc:

            return Response(
                {
                    "detail": str(exc)
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        ride = serializer.save(

            passenger=request.user,

            fare=fare,

            service_fee=service_fee,

            driver_earning=driver_earning,

            payment_status="pending",

            status="pending",
        )


        # ========================================================
        # FIND AND NOTIFY NEAREST DRIVERS
        # ========================================================

        transaction.on_commit(
            lambda ride_id=ride.ride_id:
                notify_nearest_drivers(
                    RideRequest.objects.get(
                        ride_id=ride_id
                    )
                )
        )

        return Response(
            RideRequestSerializer(ride).data,
            status=status.HTTP_201_CREATED
        )


# ============================================================
# customer.py PASSENGER ACTIVE RIDES
# ============================================================

class PassengerActiveRidesView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        rides = (
            RideRequest.objects
            .filter(
                passenger=request.user,
                status__in=[
                    "pending",
                    "accepted",
                    "arrived",
                    "started",
                ],
            )
            .select_related(
                "passenger",
                "driver",
            )
            .order_by("-created_at")
        )

        serializer = RideRequestSerializer(
            rides,
            many=True
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )


# ============================================================
# PASSENGER RIDE DETAIL
# ============================================================

class PassengerRideDetailView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, ride_id):

        ride = get_object_or_404(
            RideRequest.objects.select_related(
                "passenger",
                "driver",
            ),
            ride_id=ride_id,
            passenger=request.user,
        )

        return Response(
            RideRequestSerializer(ride).data,
            status=status.HTTP_200_OK
        )


# ============================================================
# PASSENGER CANCEL RIDE
#
# pending
#     customer CAN cancel
#
# accepted
#     customer CAN cancel
#
# arrived
#     customer CAN cancel
#
# started
#     customer CANNOT cancel
#
# completed
#     customer CANNOT cancel
#
# cancelled
#     cannot cancel again
# ============================================================

class PassengerCancelRideView(APIView):

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, ride_id):

        ride = get_object_or_404(
            RideRequest.objects.select_for_update(),
            ride_id=ride_id,
        )

        # ----------------------------------------------------
        # VERIFY PASSENGER
        # ----------------------------------------------------

        if ride.passenger_id != request.user.id:

            return Response(
                {
                    "detail":
                        "You are not the passenger "
                        "for this ride."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # ----------------------------------------------------
        # ALREADY CANCELLED
        # ----------------------------------------------------

        if ride.status == "cancelled":

            return Response(
                {
                    "detail":
                        "This ride has already been cancelled."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # COMPLETED
        # ----------------------------------------------------

        if ride.status == "completed":

            return Response(
                {
                    "detail":
                        "A completed ride cannot be cancelled."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # STARTED
        #
        # CUSTOMER CAN NO LONGER CANCEL
        # ----------------------------------------------------

        if ride.status == "started":

            return Response(
                {
                    "detail":
                        "The ride has started. "
                        "Customer cancellation is no longer available."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # CUSTOMER CAN CANCEL:
        #
        # pending
        # accepted
        # arrived
        # ----------------------------------------------------

        if ride.status in [
            "pending",
            "accepted",
            "arrived",
        ]:

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
                status=status.HTTP_200_OK,
            )

        # ----------------------------------------------------
        # FALLBACK
        # ----------------------------------------------------

        return Response(
            {
                "detail":
                    "This ride cannot be cancelled."
            },
            status=status.HTTP_400_BAD_REQUEST,
        )