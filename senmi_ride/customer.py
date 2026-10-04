# senmi_ride/customer.py

from datetime import timedelta
import secrets

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status

from senmi_ride.matching import (
    notify_nearest_drivers,
    find_nearest_drivers,
)

from .models import RideDriverAvailability, RideDriverProfile, RideRequest, RideShareToken, RideTracking
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


# ============================================================
# CREATE PUBLIC LIVE RIDE SHARE LINK
# ============================================================

class CreateRideShareView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request, ride_id):

        ride = get_object_or_404(
            RideRequest,
            ride_id=ride_id,
            passenger=request.user,
        )

        # ----------------------------------------------------
        # ONLY ACTIVE RIDES CAN BE SHARED
        # ----------------------------------------------------

        if ride.status in [
            "completed",
            "cancelled",
        ]:

            return Response(
                {
                    "detail":
                        "This ride can no longer be shared."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # REUSE EXISTING ACTIVE TOKEN
        # ----------------------------------------------------

        existing_token = (
            RideShareToken.objects
            .filter(
                ride=ride,
                revoked=False,
            )
            .order_by("-created_at")
            .first()
        )

        if existing_token:

            if (
                existing_token.expires_at is None
                or existing_token.expires_at > timezone.now()
            ):

                share_url = (
                    "https://www.senmi.com.ng/track/"
                    f"{existing_token.token}"
                )

                return Response(
                    {
                        "share_url": share_url,
                        "token": existing_token.token,
                    },
                    status=status.HTTP_200_OK,
                )

        # ----------------------------------------------------
        # CREATE NEW SECURE TOKEN
        # ----------------------------------------------------

        token = secrets.token_urlsafe(32)

        share = RideShareToken.objects.create(
            ride=ride,
            token=token,
            expires_at=timezone.now() + timedelta(hours=24),
        )

        share_url = (
            "https://www.senmi.com.ng/track/"
            f"{share.token}"
        )

        return Response(
            {
                "share_url": share_url,
                "token": share.token,
            },
            status=status.HTTP_201_CREATED,
        )



# ============================================================
# PUBLIC LIVE RIDE TRACKING
# ============================================================

class PublicRideTrackingView(APIView):

    permission_classes = [AllowAny]

    def get(self, request, token):

        share = get_object_or_404(
            RideShareToken.objects.select_related(
                "ride",
                "ride__driver",
            ),
            token=token,
            revoked=False,
        )

        # ----------------------------------------------------
        # CHECK EXPIRATION
        # ----------------------------------------------------

        if (
            share.expires_at is not None
            and timezone.now() >= share.expires_at
        ):

            return Response(
                {
                    "detail":
                        "This ride tracking link has expired."
                },
                status=status.HTTP_410_GONE,
            )

        ride = share.ride

        # ----------------------------------------------------
        # GET DRIVER PROFILE
        # ----------------------------------------------------

        driver_profile = None

        if ride.driver:

            driver_profile = (
                RideDriverProfile.objects
                .filter(
                    user=ride.driver
                )
                .first()
            )

        # ----------------------------------------------------
        # DRIVER INFORMATION
        # ----------------------------------------------------

        driver_name = None
        vehicle_number = None
        driver_image = None

        if driver_profile:

            driver_name = driver_profile.full_name

            vehicle_number = (
                driver_profile.plate_number
            )

            if driver_profile.profile_photo:

                try:
                    driver_image = (
                        driver_profile
                        .profile_photo
                        .url
                    )
                except Exception:
                    driver_image = None

        # ----------------------------------------------------
        # GET LATEST RIDE TRACKING LOCATION
        # ----------------------------------------------------

        latest_tracking = (
            RideTracking.objects
            .filter(
                ride=ride
            )
            .order_by("-timestamp")
            .first()
        )

        driver_lat = None
        driver_lng = None
        driver_location_updated_at = None

        if latest_tracking:

            driver_lat = latest_tracking.latitude
            driver_lng = latest_tracking.longitude

            driver_location_updated_at = (
                latest_tracking.timestamp.isoformat()
            )

        # ----------------------------------------------------
        # FALLBACK TO DRIVER AVAILABILITY
        # ----------------------------------------------------

        if (
            driver_lat is None
            and ride.driver
        ):

            driver_profile_for_location = (
                RideDriverProfile.objects
                .filter(
                    user=ride.driver
                )
                .first()
            )

            if driver_profile_for_location:

                availability = (
                    RideDriverAvailability.objects
                    .filter(
                        driver=driver_profile_for_location
                    )
                    .first()
                )

                if availability:

                    driver_lat = (
                        availability.latitude
                    )

                    driver_lng = (
                        availability.longitude
                    )

                    driver_location_updated_at = (
                        availability.updated_at
                        .isoformat()
                    )

        # ----------------------------------------------------
        # ETA
        # ----------------------------------------------------

        eta_minutes = None

        if (
            ride.estimated_duration_minutes
            is not None
        ):

            eta_minutes = (
                ride.estimated_duration_minutes
            )

        # ----------------------------------------------------
        # PUBLIC RESPONSE
        # ----------------------------------------------------

        return Response(
            {
                "ride_id": ride.ride_id,

                "status": ride.status,

                "pickup": {
                    "address": ride.pickup_address,
                    "lat": ride.pickup_lat,
                    "lng": ride.pickup_lng,
                },

                "destination": {
                    "address": ride.destination_address,
                    "lat": ride.destination_lat,
                    "lng": ride.destination_lng,
                },

                "driver": {
                    "name": driver_name,
                    "vehicle_number": vehicle_number,
                    "image": driver_image,
                },

                "driver_location": {
                    "lat": driver_lat,
                    "lng": driver_lng,
                    "updated_at":
                        driver_location_updated_at,
                },

                "eta_minutes": eta_minutes,

                "share_expires_at": (
                    share.expires_at.isoformat()
                    if share.expires_at
                    else None
                ),
            },
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