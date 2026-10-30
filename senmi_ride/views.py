from datetime import timedelta
import uuid

from decimal import Decimal
import logging
from django.conf import settings
from rest_framework.views import APIView

from senmi.utils import send_email
from senmi_ride.notifications import send_driver_commission_reminder


logger = logging.getLogger(__name__)

from django.core.mail import send_mail
from django.db import transaction
from django.db.models.aggregates import Avg, Count, Sum
from django.db.models.functions import ExtractHour, TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone


from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.contrib.auth import get_user_model
from django.db.models import Q

from .models import (
    RideDriverAvailability,
    RideDriverProfile,
    RideFCMDevice,
    RideRequest,
    RideTracking,
    RideRating,
    RideDriverWallet,
    RideCommissionPayment,
    RideCommissionTransaction,
)

from .serializers import (
    RideDriverProfileSerializer,
    RideRequestSerializer,
    RideTrackingSerializer,
    RideRatingSerializer,
    RideDriverWalletSerializer,
)

from .utils import (
    initialize_ride_commission_payment,
    verify_ride_commission_payment,
)

from .matching import (
    calculate_distance_km,
    MATCHING_RADIUS_KM,
)


# ============================================================
# DRIVER PROFILE
# ============================================================





class RideDriverProfileView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_object_or_404(
            RideDriverProfile,
            user=request.user,
        )

        serializer = RideDriverProfileSerializer(
            profile,
            context={"request": request},
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )

    def send_profile_email(self, profile, subject):
        try:
            send_email(
                subject=subject,
                message=(
                    "A driver has submitted his profile "
                    "for approval.\n\n"
                    f"Driver ID: {profile.driver_id}\n"
                    f"Name: {profile.full_name}\n"
                    f"Email: {profile.user.email}\n"
                    f"Phone: {profile.phone_number}\n"
                    f"Vehicle: {profile.vehicle_brand} "
                    f"{profile.vehicle_model}\n"
                    f"Plate Number: {profile.plate_number}\n"
                    f"Status: {profile.get_status_display()}\n\n"
                    "Please review the profile in the admin dashboard."
                ),
                recipients=[settings.NOTIFY_EMAIL],
            )
        except Exception:
            logger.exception(
                "Failed to send ride driver profile email."
            )

    def post(self, request):
        profile = RideDriverProfile.objects.filter(
            user=request.user,
        ).first()

        serializer = RideDriverProfileSerializer(
            profile,
            data=request.data,
            context={"request": request},
        )

        if serializer.is_valid():
            profile = serializer.save(
                user=request.user,
                status="pending",
                is_online=False,
            )

            self.send_profile_email(
                profile,
                "New Ride Driver Profile Submitted",
            )

            return Response(
                RideDriverProfileSerializer(
                    profile,
                    context={"request": request},
                ).data,
                status=status.HTTP_200_OK,
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

    def put(self, request):
        profile = get_object_or_404(
            RideDriverProfile,
            user=request.user,
        )

        serializer = RideDriverProfileSerializer(
            profile,
            data=request.data,
            context={"request": request},
        )

        if serializer.is_valid():
            if profile.status == "rejected":
                profile = serializer.save(
                    status="pending",
                    is_online=False,
                    rejection_reason="",
                )
            else:
                profile = serializer.save()

            self.send_profile_email(
                profile,
                "Driver Profile Updated",
            )

            return Response(
                RideDriverProfileSerializer(
                    profile,
                    context={"request": request},
                ).data,
                status=status.HTTP_200_OK,
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )




# ============================================================
# AVAILABLE RIDES
# BASIC:All approved, online drivers can see Basic rides.
# PREMIUM:Only drivers with vehicle year 2009 or newer
#     can see Premium rides.
# ============================================================

class AvailableRidesView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        profile = get_object_or_404(
            RideDriverProfile,
            user=request.user,
        )

        # ----------------------------------------------------
        # DRIVER MUST BE APPROVED
        # ----------------------------------------------------

        if profile.status != "approved":

            return Response(
                {
                    "detail":
                        "Your ride driver account "
                        "is not approved."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # ----------------------------------------------------
        # DRIVER MUST BE ONLINE
        # ----------------------------------------------------

        if not profile.is_online:

            return Response(
                {
                    "detail":
                        "You must be online to "
                        "view available rides."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # DRIVER LOCATION REQUIRED
        # ----------------------------------------------------

        availability = get_object_or_404(
            RideDriverAvailability,
            driver=profile,
        )

        # ----------------------------------------------------
        # GET PENDING RIDES
        # ----------------------------------------------------

        rides = (
            RideRequest.objects
            .filter(
                status="pending",
                driver__isnull=True,
            )
            .order_by("-created_at")
        )

        results = []

        # ----------------------------------------------------
        # CALCULATE DISTANCE FOR THIS DRIVER
        # ----------------------------------------------------

        for ride in rides:

            # ------------------------------------------------
            # PREMIUM ELIGIBILITY
            #
            # Basic:
            #     No vehicle-year restriction.
            #
            # Premium:
            #     Driver must have 2009+ vehicle.
            # ------------------------------------------------

            if ride.service_type == "premium":

                try:

                    vehicle_year = int(
                        profile.vehicle_year
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    continue

                if vehicle_year < 2009:

                    continue

            try:

                distance = calculate_distance_km(

                    availability.latitude,
                    availability.longitude,

                    ride.pickup_lat,
                    ride.pickup_lng,

                )

            except (
                TypeError,
                ValueError,
            ):

                continue

            # ------------------------------------------------
            # USE SAME MATCHING RADIUS AS matching.py
            # ------------------------------------------------

            if distance <= MATCHING_RADIUS_KM:

                data = RideRequestSerializer(
                    ride
                ).data

                data["driver_distance_km"] = round(
                    distance,
                    2,
                )

                results.append(data)

        # ----------------------------------------------------
        # NEAREST FIRST
        # ----------------------------------------------------

        results.sort(
            key=lambda item:
                item["driver_distance_km"]
        )

        return Response(
            results,
            status=status.HTTP_200_OK,
        )




class AcceptRideView(APIView):

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, ride_id):

        # ----------------------------------------------------
        # LOCK DRIVER PROFILE
        #
        # This is important because it prevents the same
        # driver from accepting two rides concurrently.
        # ----------------------------------------------------

        profile = get_object_or_404(
            RideDriverProfile.objects.select_for_update(),
            user=request.user,
        )

        # ----------------------------------------------------
        # DRIVER MUST BE APPROVED
        # ----------------------------------------------------

        if profile.status != "approved":

            return Response(
                {
                    "detail":
                        "Your ride driver account "
                        "is not approved."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # ----------------------------------------------------
        # DRIVER MUST BE ONLINE
        # ----------------------------------------------------

        if not profile.is_online:

            return Response(
                {
                    "detail":
                        "You must be online to "
                        "accept a ride."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # DRIVER CAN ONLY HAVE ONE ACTIVE RIDE
        #
        # accepted
        # arrived
        # started
        # ----------------------------------------------------

        active_ride = (
            RideRequest.objects
            .filter(
                driver=request.user,
                status__in=[
                    "accepted",
                    "arrived",
                    "started",
                ],
            )
            .first()
        )

        if active_ride:

            return Response(
                {
                    "detail":
                        "You already have an active ride. "
                        "Complete or cancel your current ride "
                        "before accepting another one.",

                    "active_ride_id":
                        active_ride.ride_id,

                    "active_ride_status":
                        active_ride.status,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # LOCK DRIVER WALLET
        # ----------------------------------------------------

        wallet, created = (
            RideDriverWallet.objects
            .select_for_update()
            .get_or_create(
                driver=request.user
            )
        )

        # ----------------------------------------------------
        # BLOCK NEW RIDE ACCEPTANCE AT ₦5,000
        # ----------------------------------------------------

        if wallet.commission_balance >= Decimal("5000.00"):

            return Response(
                {
                    "detail": (
                        "Your outstanding commission has reached "
                        "₦5,000. Please make a payment before "
                        "accepting another ride."
                    ),

                    "commission_due": str(
                        wallet.commission_balance
                    ),

                    "commission_payment_required": True,
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        # ----------------------------------------------------
        # LOCK RIDE
        # ----------------------------------------------------

        ride = get_object_or_404(
            RideRequest.objects.select_for_update(),
            ride_id=ride_id,
        )

        # ----------------------------------------------------
        # RIDE MUST STILL BE PENDING
        # ----------------------------------------------------

        if ride.status != "pending":

            return Response(
                {
                    "detail":
                        "This ride is no longer available."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # RIDE MUST NOT ALREADY HAVE DRIVER
        # ----------------------------------------------------

        if ride.driver_id is not None:

            return Response(
                {
                    "detail":
                        "This ride has already been accepted."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # PREMIUM DRIVER ELIGIBILITY
        # ----------------------------------------------------

        if ride.service_type == "premium":

            try:

                vehicle_year = int(
                    profile.vehicle_year
                )

            except (
                TypeError,
                ValueError,
            ):

                return Response(
                    {
                        "detail":
                            "Your vehicle does not qualify "
                            "for Premium rides."
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            if vehicle_year < 2009:

                return Response(
                    {
                        "detail":
                            "Your vehicle must be "
                            "2009 or newer to accept "
                            "Premium rides."
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        # ----------------------------------------------------
        # ASSIGN DRIVER
        # ----------------------------------------------------

        ride.driver = request.user

        ride.status = "accepted"

        ride.save(
            update_fields=[
                "driver",
                "status",
                "updated_at",
            ]
        )

        return Response(
            RideRequestSerializer(
                ride
            ).data,
            status=status.HTTP_200_OK,
        )



# ============================================================
# DRIVER ACTIVE RIDES
# ============================================================

class DriverActiveRidesView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        rides = (
            RideRequest.objects
            .filter(
                driver=request.user,
                status__in=[
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

        return Response(
            RideRequestSerializer(
                rides,
                many=True,
            ).data,
            status=status.HTTP_200_OK,
        )


# ============================================================
# UPDATE RIDE STATUS
# ============================================================

class UpdateRideStatusView(APIView):

    permission_classes = [IsAuthenticated]

    # --------------------------------------------------------
    # DRIVER
    #
    # accepted → arrived
    # accepted → cancelled
    #
    # arrived → started
    # arrived → cancelled
    #
    # started → completed
    # started → cancelled
    # --------------------------------------------------------

    DRIVER_TRANSITIONS = {

        "accepted": [
            "arrived",
            "cancelled",
        ],

        "arrived": [
            "started",
            "cancelled",
        ],

        "started": [
            "completed",
            "cancelled",
        ],
    }

    # --------------------------------------------------------
    # CUSTOMER
    #
    # pending → cancelled
    # accepted → cancelled
    # arrived → cancelled
    #
    # STARTED:
    # customer CANNOT cancel.
    # --------------------------------------------------------

    CUSTOMER_TRANSITIONS = {

        "pending": [
            "cancelled",
        ],

        "accepted": [
            "cancelled",
        ],

        "arrived": [
            "cancelled",
        ],
    }

    @transaction.atomic
    def post(self, request, ride_id):

        # ----------------------------------------------------
        # LOCK RIDE
        # ----------------------------------------------------

        ride = get_object_or_404(
            RideRequest.objects.select_for_update(),
            ride_id=ride_id,
        )

        new_status = request.data.get(
            "status"
        )

        if not new_status:

            return Response(
                {
                    "detail":
                        "Status is required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ====================================================
        # CUSTOMER
        # ====================================================

        if ride.passenger_id == request.user.id:

            allowed = self.CUSTOMER_TRANSITIONS.get(
                ride.status,
                [],
            )

            if new_status not in allowed:

                return Response(
                    {
                        "detail":
                            f"Customer cannot change "
                            f"ride from {ride.status} "
                            f"to {new_status}."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            ride.status = new_status

            if new_status == "cancelled":

                ride.cancelled_at = timezone.now()

                ride.save(
                    update_fields=[
                        "status",
                        "cancelled_at",
                        "updated_at",
                    ]
                )

            else:

                ride.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

            return Response(
                RideRequestSerializer(
                    ride
                ).data,
                status=status.HTTP_200_OK,
            )

        # ====================================================
        # DRIVER
        # ====================================================

        if ride.driver_id == request.user.id:

            allowed = self.DRIVER_TRANSITIONS.get(
                ride.status,
                [],
            )

            if new_status not in allowed:

                return Response(
                    {
                        "detail":
                            f"Driver cannot change "
                            f"ride from {ride.status} "
                            f"to {new_status}."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # ------------------------------------------------
            # COMPLETE
            # ------------------------------------------------

            if new_status == "completed":

                ride.status = "completed"

                ride.completed_at = timezone.now()

                ride.save(
                    update_fields=[
                        "status",
                        "completed_at",
                        "updated_at",
                    ]
                )

                # --------------------------------------------
                # ADD COMMISSION TO DRIVER WALLET
                # --------------------------------------------

                wallet, created = (
                    RideDriverWallet.objects
                    .select_for_update()
                    .get_or_create(
                        driver=ride.driver
                    )
                )

                wallet.commission_balance += (
                    ride.service_fee
                    or Decimal("0.00")
                )

                wallet.save(
                    update_fields=[
                        "commission_balance",
                    ]
                )

                # --------------------------------------------
                # SEND REMINDER FROM ₦3,000
                # --------------------------------------------

                if wallet.commission_balance >= Decimal("3000.00"):

                    send_driver_commission_reminder(
                        driver=ride.driver,
                        balance=wallet.commission_balance,
                    )

            # ------------------------------------------------
            # CANCEL
            # ------------------------------------------------

            elif new_status == "cancelled":

                ride.status = "cancelled"

                ride.cancelled_at = timezone.now()

                ride.save(
                    update_fields=[
                        "status",
                        "cancelled_at",
                        "updated_at",
                    ]
                )

            # ------------------------------------------------
            # ARRIVED / STARTED
            # ------------------------------------------------

            else:

                ride.status = new_status

                ride.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

            return Response(
                RideRequestSerializer(
                    ride
                ).data,
                status=status.HTTP_200_OK,
            )

        # ====================================================
        # NOT PART OF RIDE
        # ====================================================

        return Response(
            {
                "detail":
                    "You are not part of this ride."
            },
            status=status.HTTP_403_FORBIDDEN,
        )


# ============================================================
# DRIVER LOCATION / TRACKING
# ============================================================

class RideTrackingView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request, ride_id):

        ride = get_object_or_404(
            RideRequest,
            ride_id=ride_id,
        )

        # ----------------------------------------------------
        # ONLY ASSIGNED DRIVER
        # ----------------------------------------------------

        if ride.driver_id != request.user.id:

            return Response(
                {
                    "detail":
                        "You are not the driver "
                        "for this ride."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = RideTrackingSerializer(
            data={
                "ride": ride.id,

                "latitude":
                    request.data.get(
                        "latitude"
                    ),

                "longitude":
                    request.data.get(
                        "longitude"
                    ),
            }
        )

        if serializer.is_valid():

            tracking = serializer.save(
                driver=request.user
            )

            return Response(
                RideTrackingSerializer(
                    tracking
                ).data,
                status=status.HTTP_201_CREATED,
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

    # --------------------------------------------------------
    # CUSTOMER / DRIVER GET TRACKING HISTORY
    # --------------------------------------------------------

    def get(self, request, ride_id):

        ride = get_object_or_404(
            RideRequest,
            ride_id=ride_id,
        )

        if (
            ride.passenger_id != request.user.id
            and
            ride.driver_id != request.user.id
        ):

            return Response(
                {
                    "detail":
                        "You are not part of this ride."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        tracking = (
            RideTracking.objects
            .filter(
                ride=ride
            )
            .order_by("-timestamp")
        )

        serializer = RideTrackingSerializer(
            tracking,
            many=True,
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


# ============================================================
# RATING
# ============================================================

class RideRatingView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request, ride_id):

        ride = get_object_or_404(
            RideRequest,
            ride_id=ride_id,
        )

        if ride.passenger_id != request.user.id:

            return Response(
                {
                    "detail":
                        "Only the passenger can "
                        "rate this ride."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if ride.status != "completed":

            return Response(
                {
                    "detail":
                        "You can only rate a "
                        "completed ride."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not ride.driver:

            return Response(
                {
                    "detail":
                        "This ride has no driver."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if RideRating.objects.filter(
            ride=ride
        ).exists():

            return Response(
                {
                    "detail":
                        "This ride has already "
                        "been rated."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        rating_value = request.data.get(
            "rating"
        )

        comment = request.data.get(
            "comment",
            ""
        )

        try:

            rating_value = int(
                rating_value
            )

        except (
            TypeError,
            ValueError,
        ):

            return Response(
                {
                    "detail":
                        "Rating must be a number "
                        "from 1 to 5."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if rating_value < 1 or rating_value > 5:

            return Response(
                {
                    "detail":
                        "Rating must be between "
                        "1 and 5."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        rating = RideRating.objects.create(
            ride=ride,
            passenger=request.user,
            driver=ride.driver,
            rating=rating_value,
            comment=comment,
        )

        # ------------------------------------------------------------
        # UPDATE DRIVER RATING
        # ------------------------------------------------------------

        driver_profile = ride.driver.ride_driver_profile

        rating_stats = RideRating.objects.filter(
            driver=ride.driver
        ).aggregate(
            average_rating=Avg("rating"),
            total_ratings=Count("id"),
        )

        driver_profile.rating = round(
            rating_stats["average_rating"] or 0,
            2,
        )

        driver_profile.rating_count = (
            rating_stats["total_ratings"] or 0
        )

        driver_profile.save(
            update_fields=[
                "rating",
                "rating_count",
            ]
        )

        return Response(
            RideRatingSerializer(
                rating
            ).data,
            status=status.HTTP_201_CREATED,
        )

    
# ============================================================
# DRIVER WALLET
# ============================================================

class RideDriverWalletView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        wallet, created = (
            RideDriverWallet.objects
            .get_or_create(
                driver=request.user
            )
        )

        return Response(
            RideDriverWalletSerializer(
                wallet
            ).data,
            status=status.HTTP_200_OK,
        )


# ============================================================
# DRIVER → SENMI COMMISSION PAYMENT
# ============================================================

# ============================================================
# DRIVER → SENMI COMMISSION PAYMENT
#
# Driver pays the ENTIRE outstanding commission balance.
#
# This payment is not tied to one specific ride.
# RideCommissionPayment.ride therefore remains NULL.
# ============================================================

class RideCommissionPaymentView(APIView):

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):

        payment_method = request.data.get(
            "payment_method",
            "card",
        )

        # ----------------------------------------------------
        # ALLOWED PAYSTACK PAYMENT METHODS
        # ----------------------------------------------------

        allowed_methods = {
            "card",
            "bank",
            "bank_transfer",
            "ussd",
        }

        if payment_method not in allowed_methods:

            return Response(
                {
                    "detail":
                        "Invalid commission payment method."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # LOCK DRIVER WALLET
        # ----------------------------------------------------

        wallet, created = (
            RideDriverWallet.objects
            .select_for_update()
            .get_or_create(
                driver=request.user
            )
        )

        # ----------------------------------------------------
        # GET OUTSTANDING BALANCE
        # ----------------------------------------------------

        amount = (
            wallet.commission_balance
            or Decimal("0.00")
        )

        if amount <= Decimal("0.00"):

            return Response(
                {
                    "detail":
                        "You have no outstanding commission.",

                    "commission_due":
                        "0.00",

                    "commission_payment_required":
                        False,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # EXISTING PENDING SETTLEMENT PAYMENT
        #
        # Reuse it instead of creating duplicate Paystack
        # transactions.
        # ----------------------------------------------------

        existing_payment = (
            RideCommissionPayment.objects
            .filter(
                driver=request.user,
                ride__isnull=True,
                status="pending",
            )
            .order_by("-created_at")
            .first()
        )

        if existing_payment:

            # If the payment amount still equals the current
            # outstanding balance, reuse the payment.
            if existing_payment.amount == amount:

                if (
                    existing_payment.payment_method
                    != payment_method
                ):

                    existing_payment.payment_method = (
                        payment_method
                    )

                    existing_payment.save(
                        update_fields=[
                            "payment_method",
                            "updated_at",
                        ]
                    )

                return Response(
                    {
                        "payment_id":
                            existing_payment.id,

                        "amount":
                            str(
                                existing_payment.amount
                            ),

                        "payment_method":
                            existing_payment.payment_method,

                        "reference":
                            existing_payment.reference,

                        "payment_url":
                            existing_payment.payment_url,

                        "access_code":
                            existing_payment.access_code,

                        "status":
                            existing_payment.status,

                        "commission_due":
                            str(
                                wallet.commission_balance
                            ),

                        "message":
                            "Existing commission payment found.",
                    },
                    status=status.HTTP_200_OK,
                )

            # ------------------------------------------------
            # Safety:
            # If an old pending payment has a different
            # amount, don't create another payment.
            # ------------------------------------------------

            return Response(
                {
                    "detail":
                        "You already have a pending "
                        "commission payment. Please complete "
                        "or verify that payment first.",

                    "reference":
                        existing_payment.reference,

                    "amount":
                        str(
                            existing_payment.amount
                        ),

                    "commission_due":
                        str(
                            wallet.commission_balance
                        ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        # ----------------------------------------------------
        # CREATE UNIQUE REFERENCE
        # ----------------------------------------------------

        reference = (
            "SENMI-RIDE-"
            f"{uuid.uuid4().hex[:20].upper()}"
        )

        # ----------------------------------------------------
        # CREATE SETTLEMENT PAYMENT
        #
        # ride=None because this payment settles the
        # driver's total outstanding commission balance.
        # ----------------------------------------------------

        payment = RideCommissionPayment.objects.create(
            driver=request.user,
            ride=None,
            amount=amount,
            payment_method=payment_method,
            reference=reference,
            status="pending",
        )

        # ----------------------------------------------------
        # INITIALIZE PAYSTACK
        # ----------------------------------------------------

        try:

            paystack_data = (
                initialize_ride_commission_payment(
                    payment=payment,
                    email=request.user.email,
                )
            )

        except Exception as exc:

            payment.delete()

            return Response(
                {
                    "detail":
                        str(exc)
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # ----------------------------------------------------
        # SAVE PAYSTACK DATA
        # ----------------------------------------------------

        payment.payment_url = (
            paystack_data.get(
                "authorization_url"
            )
        )

        payment.access_code = (
            paystack_data.get(
                "access_code"
            )
        )

        returned_reference = (
            paystack_data.get(
                "reference"
            )
        )

        if returned_reference:

            payment.reference = (
                returned_reference
            )

        payment.save(
            update_fields=[
                "reference",
                "payment_url",
                "access_code",
                "updated_at",
            ]
        )

        # ----------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------

        return Response(
            {
                "payment_id":
                    payment.id,

                "amount":
                    str(payment.amount),

                "payment_method":
                    payment.payment_method,

                "reference":
                    payment.reference,

                "payment_url":
                    payment.payment_url,

                "access_code":
                    payment.access_code,

                "status":
                    payment.status,

                "commission_due":
                    str(
                        wallet.commission_balance
                    ),

                "commission_payment_required":
                    True,

                "message":
                    "Paystack commission payment initialized.",
            },
            status=status.HTTP_201_CREATED,
        )

    

# ============================================================
# COMPLETE COMMISSION PAYMENT
# ============================================================

def complete_ride_commission_payment(payment, paystack_data=None):

    if payment.status == "paid":
        return payment

    expected_amount = int(
        payment.amount * Decimal("100")
    )

    if paystack_data is not None:

        paystack_amount = paystack_data.get("amount")

        if paystack_amount is None:
            raise ValueError(
                "Paystack did not return a payment amount."
            )

        if int(paystack_amount) != expected_amount:
            raise ValueError(
                "Paystack payment amount does not match "
                "the commission payment."
            )

        if paystack_data.get("currency") != "NGN":
            raise ValueError(
                "Invalid payment currency."
            )

        if paystack_data.get("reference") != payment.reference:
            raise ValueError(
                "Paystack reference does not match."
            )

    wallet, created = (
        RideDriverWallet.objects
        .select_for_update()
        .get_or_create(driver=payment.driver)
    )

    outstanding_balance = (
        wallet.commission_balance or Decimal("0.00")
    )

    # Do not allow a payment to exceed the current balance.
    if payment.amount > outstanding_balance:
        raise ValueError(
            "Commission payment amount exceeds "
            "the driver's current outstanding balance."
        )

    now = timezone.now()

    # Mark only rides completed before this payment was created.
    RideRequest.objects.filter(
        driver=payment.driver,
        status="completed",
        commission_paid=False,
        completed_at__lte=payment.created_at,
    ).update(
        commission_paid=True,
        commission_paid_at=now,
        updated_at=now,
    )

    payment.status = "paid"
    payment.paid_at = now
    payment.save(
        update_fields=[
            "status",
            "paid_at",
            "updated_at",
        ]
    )

    RideCommissionTransaction.objects.get_or_create(
        payment=payment,
        defaults={
            "driver": payment.driver,
            "amount": payment.amount,
            "reference": (
                "SENMI-RIDE-TXN-"
                f"{uuid.uuid4().hex[:20].upper()}"
            ),
        },
    )

    # Deduct only the amount actually paid.
    # Any new commission remains outstanding.
    wallet.commission_balance = (
        outstanding_balance - payment.amount
    )

    wallet.total_commission_paid = (
        wallet.total_commission_paid + payment.amount
    )

    wallet.save(
        update_fields=[
            "commission_balance",
            "total_commission_paid",
        ]
    )

    return payment


# ============================================================
# VERIFY DRIVER COMMISSION PAYMENT
# ============================================================

class VerifyRideCommissionPaymentView(APIView):

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, reference):

        payment = get_object_or_404(
            RideCommissionPayment.objects.select_for_update(),
            reference=reference,
        )

        # ----------------------------------------------------
        # ONLY OWNER DRIVER
        # ----------------------------------------------------

        if payment.driver_id != request.user.id:

            return Response(
                {
                    "detail":
                        "You cannot verify this payment."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # ----------------------------------------------------
        # ALREADY PAID
        # ----------------------------------------------------

        if payment.status == "paid":

            return Response(
                {
                    "message":
                        "This commission has already "
                        "been paid.",

                    "reference":
                        payment.reference,

                    "commission_paid":
                        True,
                },
                status=status.HTTP_200_OK,
            )

        # ----------------------------------------------------
        # VERIFY PAYSTACK
        # ----------------------------------------------------

        try:

            result = (
                verify_ride_commission_payment(
                    payment.reference
                )
            )

        except Exception as exc:

            return Response(
                {
                    "detail":
                        str(exc)
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # ----------------------------------------------------
        # NOT SUCCESSFUL
        # ----------------------------------------------------

        if not result["success"]:

            data = result.get(
                "data",
                {}
            )

            paystack_status = data.get(
                "status"
            )

            if paystack_status in [
                "failed",
                "abandoned",
            ]:

                payment.status = "failed"

                payment.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

            return Response(
                {
                    "detail":
                        "Paystack payment has not "
                        "been successfully confirmed.",

                    "paystack_status":
                        paystack_status,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # VERIFY REFERENCE
        # ----------------------------------------------------

        paystack_data = result.get(
            "data",
            {}
        )

        if (
            paystack_data.get("reference")
            != payment.reference
        ):

            return Response(
                {
                    "detail":
                        "Paystack reference does not "
                        "match this payment."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # COMPLETE PAYMENT
        # ----------------------------------------------------

        try:

            payment = (
                complete_ride_commission_payment(
                    payment,
                    paystack_data,
                )
            )

        except ValueError as exc:

            return Response(
                {
                    "detail":
                        str(exc)
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        transaction_record = (
            RideCommissionTransaction.objects
            .get(
                payment=payment
            )
        )

        wallet = (
            RideDriverWallet.objects
            .get(
                driver=request.user
            )
        )

        return Response(
            {
                "message":
                    "Commission payment successful.",

                "payment":
                    payment.reference,

                "transaction":
                    transaction_record.reference,

                "amount":
                    str(payment.amount),

                "wallet_total_commission_paid":
                    str(
                        wallet.total_commission_paid
                    ),

                "commission_paid":
                    True,
            },
            status=status.HTTP_200_OK,
        )


# ============================================================
# DRIVER RIDE HISTORY
# ============================================================

class DriverRideHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rides = (
            RideRequest.objects
            .filter(driver=request.user)
            .filter(status__in=["completed", "cancelled"])
            .order_by("-created_at")
        )

        data = []

        for ride in rides:
            data.append({
                "id": ride.id,
                "ride_id": ride.ride_id,
                "passenger_name": (
                    ride.passenger.get_full_name().strip()
                    or ride.passenger.username),
                "passenger_phone": ride.passenger.phone_number or "",
                "status": ride.status,

                "pickup_address": ride.pickup_address,
                "destination_address": ride.destination_address,

                "pickup_lat": float(ride.pickup_lat or 0),
                "pickup_lng": float(ride.pickup_lng or 0),

                "destination_lat": float(ride.destination_lat or 0),
                "destination_lng": float(ride.destination_lng or 0),

                "estimated_distance_km": float(
                    ride.estimated_distance_km or 0
                ),

                "estimated_duration_minutes": (
                    ride.estimated_duration_minutes or 0
                ),

                "fare": float(ride.fare or 0),
                "service_fee": float(ride.service_fee or 0),
                "driver_earning": float(ride.driver_earning or 0),

                "payment_method": ride.payment_method,
                "payment_status": ride.payment_status,

                "commission_paid": ride.commission_paid,

                "created_at": (
                    ride.created_at.isoformat()
                    if ride.created_at
                    else None
                ),

                "completed_at": (
                    ride.completed_at.isoformat()
                    if ride.completed_at
                    else None
                ),

                "cancelled_at": (
                    ride.cancelled_at.isoformat()
                    if ride.cancelled_at
                    else None
                ),
            })

        return Response(
            data,
            status=status.HTTP_200_OK,
        )



# ============================================================
# DRIVER DELETE RIDE HISTORY
# ============================================================

class DriverDeleteRideHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, ride_id):
        try:
            ride = RideRequest.objects.get(
                ride_id=ride_id,
                driver=request.user,
                status__in=["completed", "cancelled"],
            )
        except RideRequest.DoesNotExist:
            return Response(
                {
                    "detail": "Ride history not found."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        ride.delete()

        return Response(
            {
                "detail": "Ride history deleted successfully."
            },
            status=status.HTTP_204_NO_CONTENT,
        )# ============================================================
# DRIVER DELETE RIDE HISTORY
# ============================================================

class DriverDeleteRideHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, ride_id):
        # ----------------------------------------------------
        # CHECK DRIVER'S OUTSTANDING COMMISSION FIRST
        # ----------------------------------------------------

        try:
            wallet = RideDriverWallet.objects.get(
                driver=request.user
            )

            commission_due = wallet.commission_balance or Decimal("0.00")

        except RideDriverWallet.DoesNotExist:
            # No wallet means no outstanding commission.
            commission_due = Decimal("0.00")

        # ----------------------------------------------------
        # DRIVER MUST PAY COMMISSION BEFORE DELETING HISTORY
        # ----------------------------------------------------

        if commission_due > Decimal("0.00"):
            return Response(
                {
                    "detail": (
                        f"Please pay your outstanding commission due "
                        f"of ₦{commission_due:,.2f} before deleting "
                        f"ride history."
                    ),
                    "commission_due": float(commission_due),
                    "can_delete": False,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # ----------------------------------------------------
        # FIND ONLY THIS DRIVER'S COMPLETED/CANCELLED RIDE
        # ----------------------------------------------------

        try:
            ride = RideRequest.objects.get(
                ride_id=ride_id,
                driver=request.user,
                status__in=["completed", "cancelled"],
            )

        except RideRequest.DoesNotExist:
            return Response(
                {
                    "detail": "Ride history not found."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # ----------------------------------------------------
        # COMMISSION IS ZERO → DELETE RIDE
        # ----------------------------------------------------

        ride.delete()

        return Response(
            {
                "detail": "Ride history deleted successfully.",
                "can_delete": True,
            },
            status=status.HTTP_204_NO_CONTENT,
        )

    
# ============================================================
# DRIVER STATS
# ============================================================

class DriverStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()

        today_rides = RideRequest.objects.filter(
            driver=request.user,
            created_at__date=today,
        )

        completed_today = today_rides.filter(
            status="completed"
        )

        today_earnings = (
            completed_today.aggregate(
                total=Sum("driver_earning")
            )["total"]
            or Decimal("0.00")
        )

        total_earnings = (
            RideRequest.objects
            .filter(
                driver=request.user,
                status="completed",
            )
            .aggregate(
                total=Sum("driver_earning")
            )["total"]
            or Decimal("0.00")
        )

        total_completed_rides = RideRequest.objects.filter(
            driver=request.user,
            status="completed",
        ).count()

        return Response({
            "today_earnings": float(today_earnings),
            "completed_rides_today": completed_today.count(),
            "total_rides_today": today_rides.count(),
            "total_earnings": float(total_earnings),
            "total_completed_rides": total_completed_rides,
        }, status=status.HTTP_200_OK)


# ============================================================
# DRIVER COMMISSION PAYMENT HISTORY
# ============================================================

class DriverCommissionHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        payments = (
            RideCommissionPayment.objects
            .filter(driver=request.user)
            .order_by("-created_at")
        )

        data = []

        for payment in payments:
            data.append({
                "id": payment.id,
                "reference": payment.reference,
                "amount": float(payment.amount or 0),
                "payment_method": payment.payment_method,
                "status": payment.status,

                "ride_id": (
                    payment.ride.ride_id
                    if payment.ride
                    else None
                ),

                "paid_at": (
                    payment.paid_at.isoformat()
                    if payment.paid_at
                    else None
                ),

                "created_at": (
                    payment.created_at.isoformat()
                    if payment.created_at
                    else None
                ),
            })

        return Response(
            data,
            status=status.HTTP_200_OK,
        )


# ============================================================
# ADMIN: ALL RIDES
# ============================================================

from rest_framework.permissions import IsAdminUser

class AdminAllRidesView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        rides = (
            RideRequest.objects
            .select_related(
                "passenger",
                "driver",
                "driver__ride_driver_profile",
            )
            .prefetch_related("tracking")
            .order_by("-created_at")
        )

        data = []

        for ride in rides:
            latest_tracking = (
                ride.tracking.order_by("-timestamp").first()
            )

            driver_lat = None
            driver_lng = None
            availability = None

            if latest_tracking:
                driver_lat = latest_tracking.latitude
                driver_lng = latest_tracking.longitude

            elif ride.driver:
                availability = (
                    RideDriverAvailability.objects
                    .filter(driver__user=ride.driver)
                    .first()
                )

                if availability:
                    driver_lat = availability.latitude
                    driver_lng = availability.longitude

            # Passenger contact details
            passenger = ride.passenger

            passenger_name = "Unknown"
            passenger_phone = ""

            if passenger:
                passenger_name = (
                    passenger.get_full_name()
                    or passenger.username
                    or passenger.email
                    or "Unknown"
                )

                passenger_phone = (
                    getattr(passenger, "phone_number", "")
                    or ""
                )

            # Driver and vehicle details
            driver_name = "Not assigned"
            driver_phone = ""
            driver_profile_data = None

            if ride.driver:
                driver_name = (
                    ride.driver.get_full_name()
                    or ride.driver.username
                    or "Not assigned"
                )

                driver_email = ride.driver.email or ""

                try:
                    profile = ride.driver.ride_driver_profile

                    driver_name = (
                        profile.full_name or driver_name
                    )

                    driver_phone = (
                        profile.phone_number or ""
                    )

                    driver_profile_data = {
                        "driver_id": profile.driver_id,
                        "full_name": profile.full_name or driver_name,
                        "phone_number": driver_phone,
                        "profile_photo": (
                            profile.profile_photo.url
                            if profile.profile_photo
                            else None
                        ),
                        "vehicle_brand": profile.vehicle_brand,
                        "vehicle_model": profile.vehicle_model,
                        "vehicle_color": profile.vehicle_color,
                        "vehicle_year": profile.vehicle_year,
                        "plate_number": profile.plate_number,
                        "rating": profile.rating,
                        "rating_count": profile.rating_count,
                    }

                except RideDriverProfile.DoesNotExist:
                    driver_email = ride.driver.email or ""
                else:
                    driver_email = ride.driver.email or ""
            else:
                driver_email = ""

            data.append({
                "id": ride.id,
                "ride_id": ride.ride_id,

                "passenger": passenger_name,
                "passenger_name": passenger_name,
                "passenger_email": (
                    passenger.email or "" if passenger else ""
                ),
                "passenger_phone": passenger_phone,

                "driver": driver_name,
                "driver_email": driver_email,
                "driver_phone": driver_phone,
                "driver_profile": driver_profile_data,

                "pickup": ride.pickup_address,
                "destination": ride.destination_address,

                "pickup_address": ride.pickup_address,
                "destination_address": ride.destination_address,

                "pickup_lat": ride.pickup_lat,
                "pickup_lng": ride.pickup_lng,
                "destination_lat": ride.destination_lat,
                "destination_lng": ride.destination_lng,

                "driver_lat": driver_lat,
                "driver_lng": driver_lng,

                "estimated_distance_km": (
                    ride.estimated_distance_km
                ),
                "estimated_duration_minutes": (
                    ride.estimated_duration_minutes
                ),

                # Financial breakdown
                "fare": float(ride.fare or 0),
                "service_fee": float(ride.service_fee or 0),
                "driver_earning": float(
                    ride.driver_earning or 0
                ),

                "service_type": ride.service_type,
                "payment_method": ride.payment_method,
                "payment_status": ride.payment_status,
                "payment_reference": ride.payment_reference,
                "payment_paid_at": (
                    ride.payment_paid_at.isoformat()
                    if ride.payment_paid_at
                    else None
                ),
                "commission_paid": ride.commission_paid,
                "commission_paid_at": (
                    ride.commission_paid_at.isoformat()
                    if ride.commission_paid_at
                    else None
                ),

                "status": ride.status,

                "created_at": (
                    ride.created_at.isoformat()
                    if ride.created_at
                    else None
                ),
                "updated_at": (
                    ride.updated_at.isoformat()
                    if ride.updated_at
                    else None
                ),
                "completed_at": (
                    ride.completed_at.isoformat()
                    if ride.completed_at
                    else None
                ),
                "cancelled_at": (
                    ride.cancelled_at.isoformat()
                    if ride.cancelled_at
                    else None
                ),

                "driver_location_updated_at": (
                    latest_tracking.timestamp.isoformat()
                    if latest_tracking
                    else (
                        availability.updated_at.isoformat()
                        if availability
                        else None
                    )
                ),
            })

        return Response(data, status=status.HTTP_200_OK)

    
class AdminDriversView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        profiles = RideDriverProfile.objects.select_related(
            "user"
        ).order_by("-created_at")

        data = []

        for profile in profiles:
            driver = RideDriverProfileSerializer(
                profile,
                context={"request": request},
            ).data

            driver["email"] = profile.user.email
            driver["completed_rides"] = RideRequest.objects.filter(
                driver=profile.user,
                status="completed",
            ).count()

            data.append(driver)

        return Response(
            {"drivers": data},
            status=status.HTTP_200_OK,
        )


class AdminDriverDetailView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, driver_id):
        profile = get_object_or_404(
            RideDriverProfile.objects.select_related("user"),
            driver_id=driver_id,
        )

        data = RideDriverProfileSerializer(
            profile,
            context={"request": request},
        ).data

        data["email"] = profile.user.email
        data["completed_rides"] = RideRequest.objects.filter(
            driver=profile.user,
            status="completed",
        ).count()

        return Response(data, status=status.HTTP_200_OK)




class AdminDriverStatusView(APIView):
    permission_classes = [IsAdminUser]

    def patch(self, request, driver_id):
        profile = get_object_or_404(
            RideDriverProfile.objects.select_related("user"),
            driver_id=driver_id,
        )

        new_status = request.data.get("status")
        allowed_statuses = ["pending", "approved", "rejected"]

        if new_status not in allowed_statuses:
            return Response(
                {
                    "error": (
                        "Invalid status. Use pending, approved, or rejected."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_status = profile.status

        profile.status = new_status
        profile.save(update_fields=["status"])

        # Email the driver when their application is approved.
        if new_status == "approved" and old_status != "approved":
            try:
                if profile.user.email:
                    send_email(
                        subject="Your Senmi Application Is Approved",
                        message=(
                            f"Hello Sir,\n\n"
                            "Your Senmi driver application has been approved. "
                            "Welcome to Senmi!\n\n"
                            "Best regards,\n"
                            "The Senmi Team"
                        ),
                        recipients=[profile.user.email],
                    )
                else:
                    logger.warning(
                        "No email address for driver %s",
                        driver_id,
                    )
            except Exception:
                logger.exception(
                    "Approval email failed for driver %s",
                    driver_id,
                )

        # Email the driver when their application is rejected.
        if new_status == "rejected" and old_status != "rejected":
            try:
                if profile.user.email:
                    send_email(
                        subject="Update on Your Senmi Driver Application",
                        message=(
                            "Hello Sir,\n\n"
                            "Your Senmi driver application has been rejected. "
                            "Please contact our support team for more information.\n\n"
                            "Best regards,\n"
                            "The Senmi Team"
                        ),
                        recipients=[profile.user.email],
                    )
            except Exception:
                logger.exception(
                    "Rejection email failed for driver %s",
                    driver_id,
                )

        return Response(
            {
                "message": f"Driver status updated to {new_status}.",
                "driver_id": profile.driver_id,
                "status": profile.status,
            },
            status=status.HTTP_200_OK,
        )



# ============================================================
# ADMIN: ALL CUSTOMERS
# ============================================================


class AdminCustomersView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        User = get_user_model()

        customers = User.objects.filter(
            role="customer"
        ).order_by("-date_joined")

        data = []

        for customer in customers:
            # =========================================
            # ALL RIDES FOR THIS CUSTOMER
            # =========================================
            rides = RideRequest.objects.filter(
                passenger=customer
            ).order_by("-created_at")

            completed_rides = rides.filter(
                status="completed"
            )

            totals = completed_rides.aggregate(
                total_spent=Sum("fare")
            )

            # =========================================
            # LATEST FIVE RIDES
            # =========================================
            recent_rides = []

            for ride in rides[:5]:
                recent_rides.append({
                    "id": ride.ride_id,
                    "ride_id": ride.ride_id,
                    "status": ride.status,
                    "service_type": ride.service_type,

                    # Passenger details
                    "passenger": (
                        ride.passenger.get_full_name().strip()
                        or ride.passenger.username
                        or ride.passenger.email
                        or "Unknown"
                    ),
                    "passenger_phone": (
                        getattr(ride.passenger, "phone_number", "") or ""
                    ),

                    # Driver details
                    "driver": (
                        (
                            ride.driver.ride_driver_profile.full_name
                            or ride.driver.get_full_name()
                            or ride.driver.username
                        )
                        if ride.driver else "Not assigned"
                    ),
                    "driver_phone": (
                        ride.driver.ride_driver_profile.phone_number
                        if ride.driver and hasattr(
                            ride.driver, "ride_driver_profile"
                        )
                        else ""
                    ),

                    # Pickup
                    "pickup_address": ride.pickup_address,
                    "pickup_lat": ride.pickup_lat,
                    "pickup_lng": ride.pickup_lng,

                    # Destination
                    "destination_address": ride.destination_address,
                    "destination_lat": ride.destination_lat,
                    "destination_lng": ride.destination_lng,

                    # Financial breakdown
                    "fare": str(ride.fare or 0),
                    "service_fee": str(ride.service_fee or 0),
                    "driver_earning": str(ride.driver_earning or 0),

                    # Payment details
                    "payment_method": ride.payment_method,
                    "payment_status": ride.payment_status,
                    "commission_paid": ride.commission_paid,

                    # Dates
                    "created_at": (
                        ride.created_at.isoformat()
                        if ride.created_at else None
                    ),
                    "completed_at": (
                        ride.completed_at.isoformat()
                        if ride.completed_at else None
                    ),
                    "cancelled_at": (
                        ride.cancelled_at.isoformat()
                        if ride.cancelled_at else None
                    ),
                })

            # =========================================
            # CUSTOMER INFORMATION
            # =========================================
            data.append({
                "id": customer.user_id,
                "name": (
                    customer.get_full_name().strip()
                    or customer.username
                ),
                "email": customer.email,
                "phone": customer.phone_number,
                "status": (
                    "Active"
                    if customer.is_active
                    else "Suspended"
                ),
                "joined": (
                    customer.date_joined.isoformat()
                    if customer.date_joined
                    else None
                ),

                # Ride statistics
                "total_rides": rides.count(),
                "rides": completed_rides.count(),

                "pending_rides": rides.filter(
                    status="pending"
                ).count(),

                "cancelled_rides": rides.filter(
                    status="cancelled"
                ).count(),

                "active_rides": rides.filter(
                    status__in=[
                        "accepted",
                        "arrived",
                        "started",
                    ]
                ).count(),

                # Completed-ride spending
                "spent": str(
                    totals["total_spent"] or 0
                ),

                # Latest five rides, including coordinates
                "recent_rides": recent_rides,
            })

        return Response(
            data,
            status=status.HTTP_200_OK
        )


class AdminDriverActivityView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, driver_id):
        profile = get_object_or_404(
            RideDriverProfile.objects.select_related("user"),
            driver_id=driver_id,
        )

        # Only rides assigned to this driver's user account.
        rides = (
            RideRequest.objects
            .filter(driver=profile.user)
            .select_related("passenger", "driver")
            .prefetch_related("tracking")
            .order_by("-created_at")
        )

        summary = rides.aggregate(
            total_rides=Count("id"),
            completed_rides=Count(
                "id", filter=Q(status="completed")
            ),
            cancelled_rides=Count(
                "id", filter=Q(status__in=["cancelled", "canceled"])
            ),
            active_rides=Count(
                "id",
                filter=Q(status__in=["accepted", "arrived", "started"])
            ),
            total_fare=Sum(
                "fare", filter=Q(status="completed")
            ),
            total_service_fee=Sum(
                "service_fee", filter=Q(status="completed")
            ),
            total_driver_earning=Sum(
                "driver_earning", filter=Q(status="completed")
            ),
        )

        ride_data = []

        for ride in rides:
            latest_tracking = ride.tracking.order_by("-timestamp").first()
            passenger = ride.passenger
            passenger_name = "Unknown"
            passenger_phone = ""

            if passenger:
                passenger_name = (
                    passenger.get_full_name()
                    or passenger.username
                    or passenger.email
                    or "Unknown"
                )
                passenger_phone = (
                    getattr(passenger, "phone_number", "") or ""
                )

            ride_data.append({
                "id": ride.id,
                "ride_id": ride.ride_id,
                "passenger": passenger_name,
                "passenger_phone": passenger_phone,
                "pickup": ride.pickup_address,
                "destination": ride.destination_address,
                "pickup_lat": ride.pickup_lat,
                "pickup_lng": ride.pickup_lng,
                "destination_lat": ride.destination_lat,
                "destination_lng": ride.destination_lng,
                "fare": float(ride.fare or 0),
                "service_fee": float(ride.service_fee or 0),
                "driver_earning": float(ride.driver_earning or 0),
                "service_type": ride.service_type,
                "payment_method": ride.payment_method,
                "payment_status": ride.payment_status,
                "commission_paid": ride.commission_paid,
                "status": ride.status,
                "created_at": (
                    ride.created_at.isoformat()
                    if ride.created_at else None
                ),
                "completed_at": (
                    ride.completed_at.isoformat()
                    if ride.completed_at else None
                ),
                "cancelled_at": (
                    ride.cancelled_at.isoformat()
                    if ride.cancelled_at else None
                ),
                "driver_lat": (
                    latest_tracking.latitude if latest_tracking else None
                ),
                "driver_lng": (
                    latest_tracking.longitude if latest_tracking else None
                ),
                "driver_location_updated_at": (
                    latest_tracking.timestamp.isoformat()
                    if latest_tracking else None
                ),
            })

        driver_data = RideDriverProfileSerializer(
            profile,
            context={"request": request},
        ).data
        driver_data["email"] = profile.user.email

        for key in (
            "total_fare",
            "total_service_fee",
            "total_driver_earning",
        ):
            summary[key] = float(summary[key] or 0)

        return Response({
            "driver": driver_data,
            "summary": summary,
            "rides": ride_data,
        }, status=status.HTTP_200_OK)




class AdminCommissionPaymentsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        payments = (
            RideCommissionPayment.objects
            .select_related("driver", "ride", "driver__ride_driver_profile")
            .order_by("-created_at")
        )

        data = []

        for payment in payments:
            driver = payment.driver

            # Get the actual driver's name from their profile first.
            try:
                profile = driver.ride_driver_profile
            except Exception:
                profile = None

            driver_name = (
                getattr(profile, "full_name", "") or
                driver.get_full_name() or
                driver.get_username() or
                driver.email or
                f"Driver #{driver.id}"
            )

            data.append({
                "id": payment.id,
                "driver_id": driver.id,
                "driver_name": driver_name,
                "driver_email": driver.email or "",
                "driver_phone": getattr(profile, "phone_number", "") or "",
                "driver_profile": {
                    "driver_id": getattr(profile, "driver_id", "") or "",
                    "full_name": driver_name,
                    "phone_number": getattr(profile, "phone_number", "") or "",
                } if profile else None,
                "ride_id": (
                    payment.ride.ride_id
                    if payment.ride
                    else None
                ),
                "amount": str(payment.amount or 0),
                "payment_method": payment.payment_method,
                "reference": payment.reference,
                "status": payment.status,
                "paid_at": (
                    payment.paid_at.isoformat()
                    if payment.paid_at
                    else None
                ),
                "created_at": (
                    payment.created_at.isoformat()
                    if payment.created_at
                    else None
                ),
            })

        return Response(data, status=status.HTTP_200_OK)



class AdminRideAnalyticsView(APIView):
    """
    Admin analytics based on actual ride and commission records.

    GET /ride/admin/analytics/?days=1
    GET /ride/admin/analytics/?days=7
    GET /ride/admin/analytics/?days=30
    GET /ride/admin/analytics/?days=90
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            days = int(request.query_params.get("days", 7))
        except (TypeError, ValueError):
            return Response(
                {"error": "days must be 1, 7, 30, or 90"},
                status=400,
            )

        if days not in (1, 7, 30, 90):
            return Response(
                {"error": "days must be 1, 7, 30, or 90"},
                status=400,
            )

        today = timezone.localdate()
        start_date = today - timedelta(days=days - 1)

        # Use the configured Django timezone for date boundaries.
        start_datetime = timezone.make_aware(
            timezone.datetime.combine(
                start_date,
                timezone.datetime.min.time(),
            ),
            timezone.get_current_timezone(),
        )
        end_datetime = timezone.make_aware(
            timezone.datetime.combine(
                today + timedelta(days=1),
                timezone.datetime.min.time(),
            ),
            timezone.get_current_timezone(),
        )

        rides = RideRequest.objects.filter(
            created_at__gte=start_datetime,
            created_at__lt=end_datetime,
        )

        # --------------------------------------------------
        # RIDE STATUS TOTALS
        # --------------------------------------------------

        status_counts = rides.aggregate(
            total=Count("id"),
            pending=Count("id", filter=Q(status="pending")),
            accepted=Count("id", filter=Q(status="accepted")),
            arrived=Count("id", filter=Q(status="arrived")),
            started=Count("id", filter=Q(status="started")),
            completed=Count("id", filter=Q(status="completed")),
            cancelled=Count("id", filter=Q(status="cancelled")),
        )

        total_rides = status_counts["total"] or 0
        completed_rides = status_counts["completed"] or 0
        cancelled_rides = status_counts["cancelled"] or 0

        completion_rate = (
            round(completed_rides / total_rides * 100, 2)
            if total_rides else 0
        )

        cancellation_rate = (
            round(cancelled_rides / total_rides * 100, 2)
            if total_rides else 0
        )

        # --------------------------------------------------
        # COMPLETED FARES AND DRIVER EARNINGS
        # --------------------------------------------------

        completed = rides.filter(status="completed")

        fare_stats = completed.aggregate(
            total_fares=Sum("fare"),
            average_fare=Avg("fare"),
            total_driver_earnings=Sum("driver_earning"),
            total_service_fees=Sum("service_fee"),
            average_distance=Avg("estimated_distance_km"),
            average_estimated_duration=Avg(
                "estimated_duration_minutes"
            ),
        )

        # --------------------------------------------------
        # DAILY RIDE ACTIVITY
        # Include days with zero rides.
        # --------------------------------------------------

        daily_rows = (
            rides
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(
                total=Count("id"),
                pending=Count("id", filter=Q(status="pending")),
                accepted=Count("id", filter=Q(status="accepted")),
                arrived=Count("id", filter=Q(status="arrived")),
                started=Count("id", filter=Q(status="started")),
                completed=Count("id", filter=Q(status="completed")),
                cancelled=Count("id", filter=Q(status="cancelled")),
                completed_fares=Sum(
                    "fare",
                    filter=Q(status="completed"),
                ),
            )
            .order_by("day")
        )

        daily_lookup = {
            row["day"].isoformat(): row
            for row in daily_rows
        }

        daily_activity = []

        for offset in range(days):
            day = start_date + timedelta(days=offset)
            key = day.isoformat()
            row = daily_lookup.get(key, {})

            daily_activity.append({
                "date": key,
                "total": row.get("total", 0),
                "pending": row.get("pending", 0),
                "accepted": row.get("accepted", 0),
                "arrived": row.get("arrived", 0),
                "started": row.get("started", 0),
                "completed": row.get("completed", 0),
                "cancelled": row.get("cancelled", 0),
                "completed_fares": float(
                    row.get("completed_fares") or 0
                ),
            })

        # --------------------------------------------------
        # CUSTOMER PAYMENT STATUS AND METHODS
        # --------------------------------------------------

        customer_payment_stats = rides.aggregate(
            pending=Count(
                "id",
                filter=Q(payment_status="pending"),
            ),
            paid=Count(
                "id",
                filter=Q(payment_status="paid"),
            ),
            failed=Count(
                "id",
                filter=Q(payment_status="failed"),
            ),
        )

        customer_payment_methods = list(
            rides.values("payment_method")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        # --------------------------------------------------
        # SENMI COMMISSION PAYMENTS
        # --------------------------------------------------

        commission_payments = RideCommissionPayment.objects.filter(
            created_at__gte=start_datetime,
            created_at__lt=end_datetime,
        )

        commission_stats = commission_payments.aggregate(
            total=Count("id"),
            pending=Count("id", filter=Q(status="pending")),
            paid=Count("id", filter=Q(status="paid")),
            failed=Count("id", filter=Q(status="failed")),
            cancelled=Count("id", filter=Q(status="cancelled")),
            paid_amount=Sum("amount", filter=Q(status="paid")),
            pending_amount=Sum("amount", filter=Q(status="pending")),
        )

        # --------------------------------------------------
        # PEAK HOURS
        # --------------------------------------------------

        peak_hours = list(
            rides
            .annotate(hour=ExtractHour("created_at"))
            .values("hour")
            .annotate(total=Count("id"))
            .order_by("-total")[:8]
        )

        # --------------------------------------------------
        # POPULAR PICKUPS AND DESTINATIONS
        # --------------------------------------------------

        popular_pickups = list(
            rides.exclude(pickup_address="")
            .values("pickup_address")
            .annotate(total=Count("id"))
            .order_by("-total")[:5]
        )

        popular_destinations = list(
            rides.exclude(destination_address="")
            .values("destination_address")
            .annotate(total=Count("id"))
            .order_by("-total")[:5]
        )

        # --------------------------------------------------
        # DRIVER PERFORMANCE
        # --------------------------------------------------

        driver_rows = (
            rides
            .filter(driver__isnull=False)
            .values("driver")
            .annotate(
                total_rides=Count("id"),
                completed_rides=Count(
                    "id",
                    filter=Q(status="completed"),
                ),
                cancelled_rides=Count(
                    "id",
                    filter=Q(status="cancelled"),
                ),
                completed_fares=Sum(
                    "fare",
                    filter=Q(status="completed"),
                ),
                driver_earnings=Sum(
                    "driver_earning",
                    filter=Q(status="completed"),
                ),
                average_distance=Avg(
                    "estimated_distance_km",
                    filter=Q(status="completed"),
                ),
            )
            .order_by("-completed_rides", "-total_rides")
        )

        driver_ids = [row["driver"] for row in driver_rows]

        profiles = {
            profile.user_id: profile
            for profile in RideDriverProfile.objects.filter(
                user_id__in=driver_ids
            )
        }

        ratings = (
            RideRating.objects
            .filter(
                driver_id__in=driver_ids,
                created_at__gte=start_datetime,
                created_at__lt=end_datetime,
            )
            .values("driver")
            .annotate(
                average_rating=Avg("rating"),
                rating_count=Count("id"),
            )
        )

        rating_lookup = {
            row["driver"]: row
            for row in ratings
        }

        from django.contrib.auth import get_user_model

        User = get_user_model()
        users = {
            user.pk: user
            for user in User.objects.filter(pk__in=driver_ids)
        }

        drivers = []

        for row in driver_rows[:10]:
            user_id = row["driver"]
            profile = profiles.get(user_id)
            rating = rating_lookup.get(user_id, {})
            user = users.get(user_id)

            drivers.append({
                "driver_id": profile.driver_id if profile else None,
                "name": (
                    profile.full_name
                    if profile and profile.full_name
                    else (
                        user.get_full_name() or user.get_username()
                        if user else "Unknown driver"
                    )
                ),
                "rides": row["total_rides"],
                "completed": row["completed_rides"],
                "cancelled": row["cancelled_rides"],
                "completed_fares": float(
                    row["completed_fares"] or 0
                ),
                "driver_earnings": float(
                    row["driver_earnings"] or 0
                ),
                "average_distance_km": float(
                    row["average_distance"] or 0
                ),
                "rating": float(
                    rating.get("average_rating")
                    or (profile.rating if profile else 0)
                    or 0
                ),
                "rating_count": rating.get(
                    "rating_count",
                    profile.rating_count if profile else 0,
                ),
                "is_online": profile.is_online if profile else False,
                "approval_status": profile.status if profile else None,
            })

        # --------------------------------------------------
        # SERVICE TYPES
        # --------------------------------------------------

        service_types = list(
            rides.values("service_type")
            .annotate(total=Count("id"))
            .order_by("-total")
        )

        # --------------------------------------------------
        # PREVIOUS-PERIOD COMPARISON
        # --------------------------------------------------

        previous_start = start_datetime - timedelta(days=days)

        previous_rides = RideRequest.objects.filter(
            created_at__gte=previous_start,
            created_at__lt=start_datetime,
        )

        previous_stats = previous_rides.aggregate(
            total=Count("id"),
            completed=Count("id", filter=Q(status="completed")),
            cancelled=Count("id", filter=Q(status="cancelled")),
        )

        previous_total = previous_stats["total"] or 0

        ride_change_percent = (
            round(
                (total_rides - previous_total) / previous_total * 100,
                2,
            )
            if previous_total else None
        )

        # --------------------------------------------------
        # RESPONSE
        # --------------------------------------------------

        return Response({
            "period": {
                "days": days,
                "start_date": start_date.isoformat(),
                "end_date": today.isoformat(),
                "timezone": timezone.get_current_timezone_name(),
            },
            "overview": {
                **status_counts,
                "completion_rate": completion_rate,
                "cancellation_rate": cancellation_rate,
                "average_fare": float(
                    fare_stats["average_fare"] or 0
                ),
                "average_distance_km": float(
                    fare_stats["average_distance"] or 0
                ),
                "average_estimated_duration_minutes": float(
                    fare_stats["average_estimated_duration"] or 0
                ),
                "completed_fares": float(
                    fare_stats["total_fares"] or 0
                ),
                "driver_earnings": float(
                    fare_stats["total_driver_earnings"] or 0
                ),
                "service_fees_from_completed_rides": float(
                    fare_stats["total_service_fees"] or 0
                ),
            },
            "comparison": {
                "previous_period_rides": previous_total,
                "previous_period_completed": (
                    previous_stats["completed"] or 0
                ),
                "previous_period_cancelled": (
                    previous_stats["cancelled"] or 0
                ),
                "ride_count_change_percent": ride_change_percent,
            },
            "daily_activity": daily_activity,
            "customer_payments": {
                "status": customer_payment_stats,
                "methods": customer_payment_methods,
            },
            "commission_payments": {
                "total": commission_stats["total"] or 0,
                "pending": commission_stats["pending"] or 0,
                "paid": commission_stats["paid"] or 0,
                "failed": commission_stats["failed"] or 0,
                "cancelled": commission_stats["cancelled"] or 0,
                "paid_amount": float(
                    commission_stats["paid_amount"] or 0
                ),
                "pending_amount": float(
                    commission_stats["pending_amount"] or 0
                ),
            },
            "peak_hours": peak_hours,
            "popular_pickups": popular_pickups,
            "popular_destinations": popular_destinations,
            "drivers": drivers,
            "service_types": service_types,
        })




class RegisterRideFCMTokenView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = str(request.data.get("token", "")).strip()

        if not token:
            return Response(
                {"success": False, "error": "FCM token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        device, created = RideFCMDevice.objects.update_or_create(
            token=token,
            defaults={
                "user": request.user,
                "is_active": True,
            },
        )

        return Response(
            {
                "success": True,
                "message": "Ride FCM token registered successfully.",
                "device_id": device.id,
                "created": created,
            },
            status=status.HTTP_200_OK,
        )
