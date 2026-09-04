from django.shortcuts import get_object_or_404
from django.db import transaction

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from .models import (
    RideDriverProfile,
    RideRequest,
    RideTracking,
    RideRating,
    RideDriverWallet,
    RideBank,
    RideWithdrawal,
)

from .serializers import (
    RideDriverProfileSerializer,
    RideRequestSerializer,
    RideTrackingSerializer,
    RideRatingSerializer,
    RideDriverWalletSerializer,
    RideBankSerializer,
    RideWithdrawalSerializer,
)


# ============================================================
# DRIVER PROFILE
# ============================================================

class RideDriverProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_object_or_404(
            RideDriverProfile,
            user=request.user
        )

        serializer = RideDriverProfileSerializer(profile)

        return Response(serializer.data)


# ============================================================
# CREATE RIDE / BOOK RIDE
# ============================================================

class CreateRideView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RideRequestSerializer(data=request.data)

        if serializer.is_valid():
            ride = serializer.save(
                passenger=request.user,
                payment_method="cash",
            )

            return Response(
                RideRequestSerializer(ride).data,
                status=status.HTTP_201_CREATED
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )


# ============================================================
# PASSENGER ACTIVE RIDES
# ============================================================

class PassengerActiveRidesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rides = RideRequest.objects.filter(
            passenger=request.user,
            status__in=[
                "pending",
                "accepted",
                "arrived",
                "started",
            ]
        ).order_by("-created_at")

        serializer = RideRequestSerializer(rides, many=True)

        return Response(serializer.data)


# ============================================================
# AVAILABLE RIDES FOR DRIVER
# ============================================================

class AvailableRidesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):

        profile = get_object_or_404(
            RideDriverProfile,
            user=request.user
        )

        if profile.status != "approved":
            return Response(
                {"detail": "Your ride driver account is not approved."},
                status=status.HTTP_403_FORBIDDEN
            )

        if not profile.is_online:
            return Response(
                {"detail": "You must be online to view available rides."},
                status=status.HTTP_400_BAD_REQUEST
            )

        rides = RideRequest.objects.filter(
            status="pending",
            driver__isnull=True,
        ).order_by("-created_at")

        serializer = RideRequestSerializer(
            rides,
            many=True
        )

        return Response(serializer.data)


# ============================================================
# ACCEPT RIDE
# ============================================================

class AcceptRideView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, ride_id):

        profile = get_object_or_404(
            RideDriverProfile,
            user=request.user
        )

        if profile.status != "approved":
            return Response(
                {"detail": "Your ride driver account is not approved."},
                status=status.HTTP_403_FORBIDDEN
            )

        if not profile.is_online:
            return Response(
                {"detail": "You must be online to accept a ride."},
                status=status.HTTP_400_BAD_REQUEST
            )

        ride = get_object_or_404(
            RideRequest.objects.select_for_update(),
            ride_id=ride_id
        )

        if ride.status != "pending":
            return Response(
                {"detail": "This ride is no longer available."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if ride.driver is not None:
            return Response(
                {"detail": "This ride has already been accepted."},
                status=status.HTTP_400_BAD_REQUEST
            )

        ride.driver = request.user
        ride.status = "accepted"
        ride.save()

        return Response(
            RideRequestSerializer(ride).data,
            status=status.HTTP_200_OK
        )


# ============================================================
# DRIVER ACTIVE RIDES
# ============================================================

class DriverActiveRidesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):

        rides = RideRequest.objects.filter(
            driver=request.user,
            status__in=[
                "accepted",
                "arrived",
                "started",
            ]
        ).order_by("-created_at")

        serializer = RideRequestSerializer(
            rides,
            many=True
        )

        return Response(serializer.data)


# ============================================================
# UPDATE RIDE STATUS
# ============================================================

class UpdateRideStatusView(APIView):
    permission_classes = [IsAuthenticated]

    ALLOWED_TRANSITIONS = {
        "accepted": ["arrived", "cancelled"],
        "arrived": ["started", "cancelled"],
        "started": ["completed"],
    }

    def post(self, request, ride_id):

        ride = get_object_or_404(
            RideRequest,
            ride_id=ride_id
        )

        if ride.driver_id != request.user.id:
            return Response(
                {"detail": "You are not the driver for this ride."},
                status=status.HTTP_403_FORBIDDEN
            )

        new_status = request.data.get("status")

        if not new_status:
            return Response(
                {"detail": "Status is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        allowed = self.ALLOWED_TRANSITIONS.get(
            ride.status,
            []
        )

        if new_status not in allowed:
            return Response(
                {
                    "detail": (
                        f"Cannot change ride from "
                        f"{ride.status} to {new_status}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        ride.status = new_status

        if new_status == "completed":
            from django.utils import timezone
            ride.completed_at = timezone.now()

        elif new_status == "cancelled":
            from django.utils import timezone
            ride.cancelled_at = timezone.now()

        ride.save()

        return Response(
            RideRequestSerializer(ride).data,
            status=status.HTTP_200_OK
        )


# ============================================================
# DRIVER LOCATION / TRACKING
# ============================================================

class RideTrackingView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, ride_id):

        ride = get_object_or_404(
            RideRequest,
            ride_id=ride_id
        )

        if ride.driver_id != request.user.id:
            return Response(
                {"detail": "You are not the driver for this ride."},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = RideTrackingSerializer(
            data={
                "ride": ride.id,
                "latitude": request.data.get("latitude"),
                "longitude": request.data.get("longitude"),
            }
        )

        if serializer.is_valid():
            tracking = serializer.save(
                driver=request.user
            )

            return Response(
                RideTrackingSerializer(tracking).data,
                status=status.HTTP_201_CREATED
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    def get(self, request, ride_id):

        ride = get_object_or_404(
            RideRequest,
            ride_id=ride_id
        )

        tracking = RideTracking.objects.filter(
            ride=ride
        ).order_by("-timestamp")

        serializer = RideTrackingSerializer(
            tracking,
            many=True
        )

        return Response(serializer.data)


# ============================================================
# RIDE RATING
# ============================================================

class RideRatingView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, ride_id):

        ride = get_object_or_404(
            RideRequest,
            ride_id=ride_id
        )

        if ride.passenger_id != request.user.id:
            return Response(
                {"detail": "Only the passenger can rate this ride."},
                status=status.HTTP_403_FORBIDDEN
            )

        if ride.status != "completed":
            return Response(
                {"detail": "You can only rate a completed ride."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not ride.driver:
            return Response(
                {"detail": "This ride has no driver."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if RideRating.objects.filter(ride=ride).exists():
            return Response(
                {"detail": "This ride has already been rated."},
                status=status.HTTP_400_BAD_REQUEST
            )

        rating_value = request.data.get("rating")
        comment = request.data.get("comment", "")

        try:
            rating_value = int(rating_value)
        except (TypeError, ValueError):
            return Response(
                {"detail": "Rating must be a number from 1 to 5."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if rating_value < 1 or rating_value > 5:
            return Response(
                {"detail": "Rating must be between 1 and 5."},
                status=status.HTTP_400_BAD_REQUEST
            )

        rating = RideRating.objects.create(
            ride=ride,
            passenger=request.user,
            driver=ride.driver,
            rating=rating_value,
            comment=comment,
        )

        return Response(
            RideRatingSerializer(rating).data,
            status=status.HTTP_201_CREATED
        )


# ============================================================
# DRIVER WALLET
# ============================================================

class RideDriverWalletView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):

        wallet, created = RideDriverWallet.objects.get_or_create(
            driver=request.user
        )

        serializer = RideDriverWalletSerializer(wallet)

        return Response(serializer.data)


# ============================================================
# DRIVER BANK
# ============================================================

class RideDriverBankView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):

        bank = get_object_or_404(
            RideBank,
            driver=request.user
        )

        return Response(
            RideBankSerializer(bank).data
        )

    def post(self, request):

        bank, created = RideBank.objects.get_or_create(
            driver=request.user
        )

        serializer = RideBankSerializer(
            bank,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():
            serializer.save()

            return Response(
                serializer.data,
                status=status.HTTP_200_OK
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )


# ============================================================
# WITHDRAWAL FOUNDATION
# ============================================================

class RideWithdrawalView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):

        withdrawals = RideWithdrawal.objects.filter(
            driver=request.user
        ).order_by("-created_at")

        serializer = RideWithdrawalSerializer(
            withdrawals,
            many=True
        )

        return Response(serializer.data)

    def post(self, request):

        amount = request.data.get("amount")

        if not amount:
            return Response(
                {"detail": "Amount is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        withdrawal = RideWithdrawal.objects.create(
            driver=request.user,
            amount=amount,
        )

        return Response(
            RideWithdrawalSerializer(withdrawal).data,
            status=status.HTTP_201_CREATED
        )