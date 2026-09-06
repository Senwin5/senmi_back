import uuid

from decimal import Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from .models import (
    RideDriverAvailability,
    RideDriverProfile,
    RideRequest,
    RideTracking,
    RideRating,
    RideDriverWallet,
    RideCommissionPayment,
    RideCommissionTransaction,
)

from .serializers import (
    RideDriverAvailabilitySerializer,
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

            serializer.save()

            return Response(
                serializer.data,
                status=status.HTTP_200_OK,
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )


# ============================================================
# AVAILABLE RIDES
#
# This is the driver's fallback HTTP list.
#
# Primary matching:
#
# customer creates ride
#        ↓
# matching.py
#        ↓
# nearest drivers notified
#
# This endpoint lets an online driver manually refresh
# nearby pending rides.
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


# ============================================================
# ACCEPT RIDE
#
# Customer has created the ride.
#
# Multiple drivers may receive the request.
#
# ONLY ONE DRIVER CAN WIN.
#
# select_for_update() locks the RideRequest row.
# ============================================================

class AcceptRideView(APIView):

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, ride_id):

        # ----------------------------------------------------
        # VERIFY DRIVER
        # ----------------------------------------------------

        profile = get_object_or_404(
            RideDriverProfile,
            user=request.user,
        )

        if profile.status != "approved":

            return Response(
                {
                    "detail":
                        "Your ride driver account "
                        "is not approved."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

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
                # ADD COMMISSION OWED TO DRIVER WALLET
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

    # --------------------------------------------------------
    # DRIVER POSTS LOCATION
    # --------------------------------------------------------

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

class RideCommissionPaymentView(APIView):

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):

        ride_id = request.data.get(
            "ride_id"
        )

        payment_method = request.data.get(
            "payment_method",
            "card",
        )

        if not ride_id:

            return Response(
                {
                    "detail":
                        "ride_id is required."
                },
                status=status.HTTP_400_BAD_REQUEST,
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
                status=status.HTTP_400_BAD_REQUEST,
            )

        ride = get_object_or_404(
            RideRequest.objects.select_for_update(),
            ride_id=ride_id,
        )

        # ----------------------------------------------------
        # ONLY DRIVER
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

        # ----------------------------------------------------
        # MUST BE COMPLETED
        # ----------------------------------------------------

        if ride.status != "completed":

            return Response(
                {
                    "detail":
                        "Commission can only be paid "
                        "after the ride is completed."
                },
                status=status.HTTP_400_BAD_REQUEST,
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
                status=status.HTTP_400_BAD_REQUEST,
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
                status=status.HTTP_400_BAD_REQUEST,
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
                },
                status=status.HTTP_200_OK,
            )

        # ----------------------------------------------------
        # CREATE REFERENCE
        # ----------------------------------------------------

        reference = (
            "SENMI-RIDE-"
            f"{uuid.uuid4().hex[:20].upper()}"
        )

        # ----------------------------------------------------
        # CREATE PAYMENT
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
                    "Paystack commission payment initialized.",
            },
            status=status.HTTP_201_CREATED,
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
    # EXPECTED PAYSTACK AMOUNT
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
    # LOCK DRIVER WALLET
    # --------------------------------------------------------

    wallet, created = (
        RideDriverWallet.objects
        .select_for_update()
        .get_or_create(
            driver=payment.driver
        )
    )

    # --------------------------------------------------------
    # DRIVER CANNOT PAY MORE THAN OWED
    # --------------------------------------------------------

    if wallet.commission_balance < payment.amount:

        raise ValueError(
            "Commission balance is lower than "
            "the payment amount."
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
    # CREATE TRANSACTION ONCE
    # --------------------------------------------------------

    RideCommissionTransaction.objects.get_or_create(

        payment=payment,

        defaults={

            "driver":
                payment.driver,

            "amount":
                payment.amount,

            "reference":
                (
                    "SENMI-RIDE-TXN-"
                    f"{uuid.uuid4().hex[:20].upper()}"
                ),
        },
    )

    # --------------------------------------------------------
    # REDUCE COMMISSION BALANCE
    # --------------------------------------------------------

    wallet.commission_balance -= (
        payment.amount
    )

    wallet.total_commission_paid += (
        payment.amount
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