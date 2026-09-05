from rest_framework import serializers

from .models import (
    RideDriverProfile,
    RideRequest,
    RideTracking,
    RideRating,
    RideDriverWallet,
    RideCommissionPayment,
    RideCommissionTransaction,
)


# ============================================================
# DRIVER PROFILE
# ============================================================

class RideDriverProfileSerializer(serializers.ModelSerializer):

    full_name = serializers.CharField(
        required=True
    )

    phone_number = serializers.CharField(
        required=True
    )

    profile_photo = serializers.ImageField(
        required=True
    )

    driver_license_photo = serializers.ImageField(
        required=True
    )

    vehicle_photo = serializers.ImageField(
        required=True
    )

    vehicle_brand = serializers.CharField(
        required=True
    )

    vehicle_model = serializers.CharField(
        required=True
    )

    plate_number = serializers.CharField(
        required=True
    )

    class Meta:
        model = RideDriverProfile

        fields = [
            "driver_id",
            "full_name",
            "phone_number",
            "profile_photo",
            "driver_license_photo",
            "vehicle_photo",
            "vehicle_brand",
            "vehicle_model",
            "vehicle_color",
            "vehicle_year",
            "plate_number",
            "is_online",
            "status",
            "rejection_reason",
            "rating",
            "rating_count",
            "created_at",
        ]

        read_only_fields = [
            "driver_id",
            "status",
            "rejection_reason",
            "rating",
            "rating_count",
            "created_at",
        ]


# ============================================================
# RIDE REQUEST
# ============================================================

class RideRequestSerializer(serializers.ModelSerializer):

    passenger_email = serializers.EmailField(
        source="passenger.email",
        read_only=True
    )

    driver_email = serializers.EmailField(
        source="driver.email",
        read_only=True
    )

    class Meta:
        model = RideRequest

        fields = [
            "id",
            "ride_id",

            "passenger",
            "passenger_email",

            "driver",
            "driver_email",

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

            # Customer → Driver
            "payment_method",
            "payment_status",
            "payment_reference",
            "payment_paid_at",

            # Driver → Senmi
            "commission_paid",
            "commission_paid_at",

            "status",

            "created_at",
            "updated_at",
            "completed_at",
            "cancelled_at",
        ]

        read_only_fields = [
            "id",
            "ride_id",

            "passenger",
            "driver",

            "fare",
            "service_fee",
            "driver_earning",

            "payment_status",
            "payment_reference",
            "payment_paid_at",

            "commission_paid",
            "commission_paid_at",

            "status",

            "created_at",
            "updated_at",
            "completed_at",
            "cancelled_at",
        ]


# ============================================================
# TRACKING
# ============================================================

class RideTrackingSerializer(serializers.ModelSerializer):

    class Meta:
        model = RideTracking

        fields = [
            "id",
            "ride",
            "driver",
            "latitude",
            "longitude",
            "timestamp",
        ]

        read_only_fields = [
            "id",
            "driver",
            "timestamp",
        ]


# ============================================================
# RATING
# ============================================================

class RideRatingSerializer(serializers.ModelSerializer):

    class Meta:
        model = RideRating

        fields = [
            "id",
            "ride",
            "passenger",
            "driver",
            "rating",
            "comment",
            "created_at",
        ]

        read_only_fields = [
            "id",
            "passenger",
            "driver",
            "created_at",
        ]


# ============================================================
# DRIVER WALLET
# ============================================================

class RideDriverWalletSerializer(serializers.ModelSerializer):

    class Meta:
        model = RideDriverWallet

        fields = [
            "id",
            "driver",
            "balance",
            "total_commission_paid",
        ]

        read_only_fields = fields



# ============================================================
# COMMISSION PAYMENT
# ============================================================

class RideCommissionPaymentSerializer(
    serializers.ModelSerializer
):

    class Meta:
        model = RideCommissionPayment

        fields = [
            "id",
            "driver",
            "ride",
            "amount",
            "payment_method",
            "reference",
            "payment_url",
            "access_code",
            "status",
            "paid_at",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "driver",
            "ride",
            "amount",
            "reference",
            "payment_url",
            "access_code",
            "status",
            "paid_at",
            "created_at",
            "updated_at",
        ]


# ============================================================
# COMMISSION TRANSACTION
# ============================================================

class RideCommissionTransactionSerializer(
    serializers.ModelSerializer
):

    class Meta:
        model = RideCommissionTransaction

        fields = [
            "id",
            "driver",
            "payment",
            "amount",
            "reference",
            "created_at",
        ]

        read_only_fields = [
            "id",
            "driver",
            "payment",
            "amount",
            "reference",
            "created_at",
        ]