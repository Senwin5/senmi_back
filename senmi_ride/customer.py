# senmi_ride/customer.py

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from senmi_ride.matching import (
    notify_nearest_drivers,
    find_nearest_drivers,
)

from .models import RideRequest
from .serializers import RideRequestSerializer
from .utils import (
    calculate_ride_fare,
    calculate_distance,
)


# ============================================================
# CUSTOMER RIDE FARE QUOTE
# ============================================================

class RideFareQuoteView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request):

        pickup_lat = request.data.get(
            "pickup_lat"
        )

        pickup_lng = request.data.get(
            "pickup_lng"
        )

        destination_lat = request.data.get(
            "destination_lat"
        )

        destination_lng = request.data.get(
            "destination_lng"
        )

        service_type = request.data.get(
            "service_type",
            "basic",
        )

        # ----------------------------------------------------
        # REQUIRED LOCATIONS
        # ----------------------------------------------------

        if (
            pickup_lat is None
            or pickup_lng is None
            or destination_lat is None
            or destination_lng is None
        ):

            return Response(
                {
                    "detail":
                        "Pickup and destination "
                        "coordinates are required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # SERVICE TYPE
        # ----------------------------------------------------

        if service_type not in [
            "basic",
            "premium",
        ]:

            return Response(
                {
                    "detail":
                        "Invalid ride service type."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # CONVERT COORDINATES
        # ----------------------------------------------------

        try:

            pickup_lat = float(
                pickup_lat
            )

            pickup_lng = float(
                pickup_lng
            )

            destination_lat = float(
                destination_lat
            )

            destination_lng = float(
                destination_lng
            )

        except (
            TypeError,
            ValueError,
        ):

            return Response(
                {
                    "detail":
                        "Invalid coordinate values."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # CALCULATE DISTANCE
        # ----------------------------------------------------

        try:

            distance_km = calculate_distance(
                pickup_lat,
                pickup_lng,
                destination_lat,
                destination_lng,
            )

        except (
            TypeError,
            ValueError,
        ):

            return Response(
                {
                    "detail":
                        "Unable to calculate ride distance."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # ESTIMATED DURATION
        #
        # Temporary estimate:
        # approximately 2 minutes per kilometre.
        # ----------------------------------------------------

        duration_minutes = max(
            1,
            int(
                (float(distance_km) * 2) + 0.5
            ),
        )

        # ----------------------------------------------------
        # CALCULATE FARE
        # ----------------------------------------------------

        try:

            (
                fare,
                service_fee,
                driver_earning,
            ) = calculate_ride_fare(
                distance_km,
                duration_minutes,
                service_type=service_type,
            )

        except ValueError as exc:

            return Response(
                {
                    "detail": str(exc)
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # RETURN QUOTE
        # ----------------------------------------------------

        return Response(
            {
                "service_type": service_type,

                "estimated_distance_km":
                    str(distance_km),

                "estimated_duration_minutes":
                    duration_minutes,

                "fare":
                    str(fare),

                "service_fee":
                    str(service_fee),

                "driver_earning":
                    str(driver_earning),
            },
            status=status.HTTP_200_OK,
        )


# ============================================================
# CUSTOMER CREATE RIDE
# ============================================================

class CreateRideView(APIView):

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):

                # ----------------------------------------------------
        # CUSTOMER CAN ONLY HAVE ONE ACTIVE RIDE
        # ----------------------------------------------------

        active_ride = (
            RideRequest.objects
            .select_for_update()
            .filter(
                passenger=request.user,
                status__in=[
                    "pending",
                    "accepted",
                    "arrived",
                    "started",
                ],
            )
            .order_by("-created_at")
            .first()
        )

        if active_ride:
            return Response(
                {
                    "detail":
                        "You already have an active ride. "
                        "Complete or cancel your current ride "
                        "before booking another one.",

                    "active_ride_id":
                        active_ride.ride_id,

                    "active_ride_status":
                        active_ride.status,
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = RideRequestSerializer(
            data=request.data
        )

        if not serializer.is_valid():

            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

        validated_data = serializer.validated_data

        # ----------------------------------------------------
        # BASIC IS THE DEFAULT
        #
        # Customer can choose:
        # "basic"
        # "premium"
        # ----------------------------------------------------

        service_type = validated_data.get(
            "service_type",
            "basic",
        )

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
                service_type=service_type,
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

            # Save customer's Basic/Premium choice.
            service_type=service_type,

            fare=fare,

            service_fee=service_fee,

            driver_earning=driver_earning,

            payment_status="pending",

            status="pending",
        )

        # ====================================================
        # PREMIUM AVAILABILITY CHECK
        #
        # Premium requires an eligible vehicle.
        # ====================================================

        if service_type == "premium":

            eligible_drivers = find_nearest_drivers(
                ride
            )

            if not eligible_drivers:

                ride.delete()

                return Response(
                    {
                        "detail":
                            "Premium is not available "
                            "right now. Please choose "
                            "Basic to continue."
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        # ====================================================
        # FIND AND NOTIFY NEAREST DRIVERS
        # ====================================================

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
# CUSTOMER RIDE HISTORY
#
# Returns every ride created by the logged-in customer.
#
# Includes:
# pending
# accepted
# arrived
# started
# completed
# cancelled
# ============================================================

class PassengerRideHistoryView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        rides = (
            RideRequest.objects
            .filter(
                passenger=request.user,
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
# CUSTOMER PASSENGER ACTIVE RIDES
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


    @transaction.atomic
    def patch(self, request, ride_id):

        ride = get_object_or_404(
            RideRequest.objects.select_for_update(),
            ride_id=ride_id,
            passenger=request.user,
        )

        # ----------------------------------------------------
        # RIDE STATUS
        # ----------------------------------------------------

        if ride.status not in [
            "pending",
            "accepted",
            "arrived",
        ]:

            return Response(
                {
                    "detail":
                        "The trip route can no longer be changed "
                        "after the ride has started."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # REQUIRED ROUTE DATA
        # ----------------------------------------------------

        pickup_address = request.data.get(
            "pickup_address"
        )

        destination_address = request.data.get(
            "destination_address"
        )

        pickup_lat = request.data.get(
            "pickup_lat"
        )

        pickup_lng = request.data.get(
            "pickup_lng"
        )

        destination_lat = request.data.get(
            "destination_lat"
        )

        destination_lng = request.data.get(
            "destination_lng"
        )

        if (
            pickup_address is None
            or destination_address is None
            or pickup_lat is None
            or pickup_lng is None
            or destination_lat is None
            or destination_lng is None
        ):

            return Response(
                {
                    "detail":
                        "Pickup and destination "
                        "information are required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # CONVERT COORDINATES
        # ----------------------------------------------------

        try:

            pickup_lat = float(
                pickup_lat
            )

            pickup_lng = float(
                pickup_lng
            )

            destination_lat = float(
                destination_lat
            )

            destination_lng = float(
                destination_lng
            )

        except (
            TypeError,
            ValueError,
        ):

            return Response(
                {
                    "detail":
                        "Invalid pickup or destination coordinates."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # CALCULATE NEW DISTANCE
        # ----------------------------------------------------

        try:

            distance_km = calculate_distance(
                pickup_lat,
                pickup_lng,
                destination_lat,
                destination_lng,
            )

        except (
            TypeError,
            ValueError,
        ):

            return Response(
                {
                    "detail":
                        "Unable to calculate ride distance."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # ESTIMATED DURATION
        #
        # Keep the same calculation used by RideFareQuoteView.
        # ----------------------------------------------------

        duration_minutes = max(
            1,
            int(
                (float(distance_km) * 2) + 0.5
            ),
        )

        # ----------------------------------------------------
        # RECALCULATE FARE
        # ----------------------------------------------------

        try:

            (
                fare,
                service_fee,
                driver_earning,
            ) = calculate_ride_fare(
                distance_km,
                duration_minutes,
                service_type=ride.service_type,
            )

        except ValueError as exc:

            return Response(
                {
                    "detail": str(exc)
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # UPDATE RIDE
        # ----------------------------------------------------

        ride.pickup_address = pickup_address
        ride.destination_address = destination_address

        ride.pickup_lat = pickup_lat
        ride.pickup_lng = pickup_lng

        ride.destination_lat = destination_lat
        ride.destination_lng = destination_lng

        ride.estimated_distance_km = distance_km
        ride.estimated_duration_minutes = duration_minutes

        ride.fare = fare
        ride.service_fee = service_fee
        ride.driver_earning = driver_earning

        ride.save(
            update_fields=[
                "pickup_address",
                "destination_address",
                "pickup_lat",
                "pickup_lng",
                "destination_lat",
                "destination_lng",
                "estimated_distance_km",
                "estimated_duration_minutes",
                "fare",
                "service_fee",
                "driver_earning",
                "updated_at",
            ]
        )

        # ----------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------

        return Response(
            RideRequestSerializer(ride).data,
            status=status.HTTP_200_OK,
        )

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