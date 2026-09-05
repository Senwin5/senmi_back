import hashlib
import hmac
import json
import uuid

from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

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
    calculate_ride_fare,
    initialize_ride_commission_payment,
    verify_ride_commission_payment,
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

        serializer = RideDriverProfileSerializer(
            profile,
            context={"request": request}
        )

        return Response(serializer.data)

    def put(self, request):

        profile = get_object_or_404(
            RideDriverProfile,
            user=request.user
        )

        serializer = RideDriverProfileSerializer(
            profile,
            data=request.data,
            context={"request": request}
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
# CREATE RIDE
#
# CUSTOMER → DRIVER
#
# Customer chooses:
# cash
# card
# bank_transfer
#
# No Paystack payment happens here.
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
        )

        return Response(
            RideRequestSerializer(
                ride
            ).data,
            status=status.HTTP_201_CREATED
        )


# ============================================================
# PASSENGER ACTIVE RIDES
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
                ]
            )
            .order_by("-created_at")
        )

        serializer = RideRequestSerializer(
            rides,
            many=True
        )

        return Response(
            serializer.data
        )


# ============================================================
# AVAILABLE RIDES
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
                {
                    "detail":
                        "Your ride driver account "
                        "is not approved."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        if not profile.is_online:

            return Response(
                {
                    "detail":
                        "You must be online to "
                        "view available rides."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        rides = (
            RideRequest.objects
            .filter(
                status="pending",
                driver__isnull=True,
            )
            .order_by("-created_at")
        )

        serializer = RideRequestSerializer(
            rides,
            many=True
        )

        return Response(
            serializer.data
        )


# ============================================================
# ACCEPT RIDE
#
# IMPORTANT:
#
# We do NOT check the customer's payment method.
#
# Cash is allowed.
# Card is allowed.
# Bank transfer is allowed.
#
# Driver commission is paid separately after the ride.
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
                {
                    "detail":
                        "Your ride driver account "
                        "is not approved."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        if not profile.is_online:

            return Response(
                {
                    "detail":
                        "You must be online to "
                        "accept a ride."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        ride = get_object_or_404(
            RideRequest.objects.select_for_update(),
            ride_id=ride_id
        )

        if ride.status != "pending":

            return Response(
                {
                    "detail":
                        "This ride is no longer available."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if ride.driver is not None:

            return Response(
                {
                    "detail":
                        "This ride has already been accepted."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

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
            status=status.HTTP_200_OK
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
                ]
            )
            .order_by("-created_at")
        )

        serializer = RideRequestSerializer(
            rides,
            many=True
        )

        return Response(
            serializer.data
        )


# ============================================================
# UPDATE RIDE STATUS
# ============================================================

class UpdateRideStatusView(APIView):

    permission_classes = [IsAuthenticated]

    ALLOWED_TRANSITIONS = {

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
        ],
    }

    def post(self, request, ride_id):

        ride = get_object_or_404(
            RideRequest,
            ride_id=ride_id
        )

        if ride.driver_id != request.user.id:

            return Response(
                {
                    "detail":
                        "You are not the driver "
                        "for this ride."
                },
                status=status.HTTP_403_FORBIDDEN
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
                status=status.HTTP_400_BAD_REQUEST
            )

        allowed = self.ALLOWED_TRANSITIONS.get(
            ride.status,
            []
        )

        if new_status not in allowed:

            return Response(
                {
                    "detail":
                        f"Cannot change ride from "
                        f"{ride.status} to "
                        f"{new_status}."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        ride.status = new_status

        if new_status == "completed":

            ride.completed_at = timezone.now()

            wallet, created = RideDriverWallet.objects.get_or_create(
                driver=ride.driver
            )

            wallet.commission_balance += (
                ride.service_fee or Decimal("0.00")
            )

            wallet.save(
                update_fields=[
                    "commission_balance",
                ]
            )

        elif new_status == "cancelled":

            ride.cancelled_at = timezone.now()

        ride.save()

        return Response(
            RideRequestSerializer(
                ride
            ).data,
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
                {
                    "detail":
                        "You are not the driver "
                        "for this ride."
                },
                status=status.HTTP_403_FORBIDDEN
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

        # Only passenger or assigned driver can see tracking.
        if (
            ride.passenger_id != request.user.id
            and ride.driver_id != request.user.id
        ):

            return Response(
                {
                    "detail":
                        "You are not part of this ride."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        tracking = (
            RideTracking.objects
            .filter(ride=ride)
            .order_by("-timestamp")
        )

        serializer = RideTrackingSerializer(
            tracking,
            many=True
        )

        return Response(
            serializer.data
        )


# ============================================================
# RATING
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
                {
                    "detail":
                        "Only the passenger can "
                        "rate this ride."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        if ride.status != "completed":

            return Response(
                {
                    "detail":
                        "You can only rate a "
                        "completed ride."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if not ride.driver:

            return Response(
                {
                    "detail":
                        "This ride has no driver."
                },
                status=status.HTTP_400_BAD_REQUEST
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
                status=status.HTTP_400_BAD_REQUEST
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

        except (TypeError, ValueError):

            return Response(
                {
                    "detail":
                        "Rating must be a number "
                        "from 1 to 5."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if rating_value < 1 or rating_value > 5:

            return Response(
                {
                    "detail":
                        "Rating must be between "
                        "1 and 5."
                },
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
            RideRatingSerializer(
                rating
            ).data,
            status=status.HTTP_201_CREATED
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

        serializer = RideDriverWalletSerializer(
            wallet
        )

        return Response(
            serializer.data
        )




# ============================================================
# DRIVER → SENMI COMMISSION PAYMENT
# ============================================================

class RideCommissionPaymentView(APIView):

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):

        ride_id = request.data.get(
            "ride_id"
        )

        payment_method = request.data.get(
            "payment_method",
            "card"
        )

        if not ride_id:

            return Response(
                {
                    "detail":
                        "ride_id is required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

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
                status=status.HTTP_400_BAD_REQUEST
            )

        ride = get_object_or_404(
            RideRequest.objects.select_for_update(),
            ride_id=ride_id
        )

        # ----------------------------------------------------
        # ONLY DRIVER CAN PAY COMMISSION
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
        # RIDE MUST BE COMPLETED
        # ----------------------------------------------------

        if ride.status != "completed":

            return Response(
                {
                    "detail":
                        "Commission can only be paid "
                        "after the ride is completed."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ----------------------------------------------------
        # ALREADY PAID
        # ----------------------------------------------------

        if ride.commission_paid:

            return Response(
                {
                    "detail":
                        "Commission for this ride "
                        "has already been paid."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ----------------------------------------------------
        # COMMISSION AMOUNT
        # ----------------------------------------------------

        amount = (
            ride.service_fee
            or Decimal("0.00")
        )

        if amount <= Decimal("0.00"):

            return Response(
                {
                    "detail":
                        "There is no commission "
                        "to pay for this ride."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ----------------------------------------------------
        # EXISTING PENDING PAYMENT
        # ----------------------------------------------------

        existing_payment = (
            RideCommissionPayment.objects
            .filter(
                ride=ride,
                driver=request.user,
                status="pending",
            )
            .order_by("-created_at")
            .first()
        )

        if existing_payment:

            # If user requests another method, update it
            # before returning the existing payment.
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

                    "ride_id":
                        ride.ride_id,

                    "amount":
                        str(existing_payment.amount),

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
                },
                status=status.HTTP_200_OK
            )

        # ----------------------------------------------------
        # GENERATE PAYSTACK REFERENCE
        # ----------------------------------------------------

        reference = (
            "SENMI-RIDE-"
            f"{uuid.uuid4().hex[:20].upper()}"
        )

        # ----------------------------------------------------
        # CREATE PAYMENT RECORD
        # ----------------------------------------------------

        payment = RideCommissionPayment.objects.create(
            driver=request.user,
            ride=ride,
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
                status=status.HTTP_502_BAD_GATEWAY
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

        # Paystack should return the same reference.
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

        return Response(
            {
                "payment_id":
                    payment.id,

                "ride_id":
                    ride.ride_id,

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

                "message":
                    "Paystack commission payment initialized."
            },
            status=status.HTTP_201_CREATED
        )



# ============================================================
# COMPLETE COMMISSION PAYMENT
# ============================================================

def complete_ride_commission_payment(
    payment,
    paystack_data=None,
):

    if payment.status == "paid":
        return payment

    # --------------------------------------------------------
    # CHECK PAYSTACK AMOUNT
    # --------------------------------------------------------

    expected_amount = int(
        payment.amount * Decimal("100")
    )

    if paystack_data is not None:

        paystack_amount = paystack_data.get(
            "amount"
        )

        if paystack_amount is None:

            raise ValueError(
                "Paystack did not return a payment amount."
            )

        if int(paystack_amount) != expected_amount:

            raise ValueError(
                "Paystack payment amount does not "
                "match the commission amount."
            )

    # --------------------------------------------------------
    # GET DRIVER COMMISSION WALLET
    #
    # commission_balance =
    # amount currently owed by driver to Senmi
    #
    # total_commission_paid =
    # cumulative commission paid by driver
    # --------------------------------------------------------

    wallet, created = RideDriverWallet.objects.get_or_create(
        driver=payment.driver
    )

    # --------------------------------------------------------
    # CHECK COMMISSION BALANCE
    # --------------------------------------------------------

    if wallet.commission_balance < payment.amount:

        raise ValueError(
            "Commission balance is lower than the payment amount."
        )

    # --------------------------------------------------------
    # MARK PAYMENT PAID
    # --------------------------------------------------------

    now = timezone.now()

    payment.status = "paid"
    payment.paid_at = now

    payment.save(
        update_fields=[
            "status",
            "paid_at",
            "updated_at",
        ]
    )

    # --------------------------------------------------------
    # MARK RIDE COMMISSION PAID
    # --------------------------------------------------------

    ride = payment.ride

    if ride:

        ride.commission_paid = True
        ride.commission_paid_at = now

        ride.save(
            update_fields=[
                "commission_paid",
                "commission_paid_at",
                "updated_at",
            ]
        )

    # --------------------------------------------------------
    # CREATE TRANSACTION RECORD ONCE
    # --------------------------------------------------------

    RideCommissionTransaction.objects.get_or_create(
        payment=payment,
        defaults={
            "driver": payment.driver,
            "amount": payment.amount,
            "reference": (
                "SENMI-RIDE-TXN-"
                f"{uuid.uuid4().hex[:20].upper()}"
            ),
        }
    )

    # --------------------------------------------------------
    # UPDATE COMMISSION WALLET
    #
    # Example:
    #
    # Before payment:
    # commission_balance = ₦3,000
    #
    # Driver pays ₦3,000
    #
    # After payment:
    # commission_balance = ₦0
    # total_commission_paid += ₦3,000
    # --------------------------------------------------------

    wallet.commission_balance -= payment.amount

    wallet.total_commission_paid += payment.amount

    wallet.save(
        update_fields=[
            "commission_balance",
            "total_commission_paid",
        ]
    )

    return payment




# ============================================================
# VERIFY DRIVER COMMISSION PAYMENT
#
# POST
# /api/ride/commission/verify/<reference>/
# ============================================================

class VerifyRideCommissionPaymentView(APIView):

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, reference):

        payment = get_object_or_404(
            RideCommissionPayment.objects.select_for_update(),
            reference=reference
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
                status=status.HTTP_403_FORBIDDEN
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
                status=status.HTTP_200_OK
            )

        # ----------------------------------------------------
        # PAYSTACK VERIFICATION
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
                status=status.HTTP_502_BAD_GATEWAY
            )

        # ----------------------------------------------------
        # PAYMENT FAILED / NOT COMPLETE
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
                status=status.HTTP_400_BAD_REQUEST
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
                status=status.HTTP_400_BAD_REQUEST
            )

        # ----------------------------------------------------
        # COMPLETE
        # ----------------------------------------------------

        try:

            payment = (
                complete_ride_commission_payment(
                    payment,
                    paystack_data
                )
            )

        except ValueError as exc:

            return Response(
                {
                    "detail":
                        str(exc)
                },
                status=status.HTTP_400_BAD_REQUEST
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
            status=status.HTTP_200_OK
        )

