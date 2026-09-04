from rest_framework import serializers
from .models import (
    RideDriverProfile,
    RideRequest,
    RideTracking,
    RideRating,
    RideDriverWallet,
    RideBank,
    RideWithdrawal,
)


class RideDriverProfileSerializer(serializers.ModelSerializer):
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
            "payment_method",
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
            "commission_paid",
            "commission_paid_at",
            "status",
            "created_at",
            "updated_at",
            "completed_at",
            "cancelled_at",
        ]


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


class RideBankSerializer(serializers.ModelSerializer):
    class Meta:
        model = RideBank
        fields = [
            "id",
            "driver",
            "account_name",
            "account_number",
            "bank_name",
            "bank_code",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "driver",
            "created_at",
            "updated_at",
        ]


class RideWithdrawalSerializer(serializers.ModelSerializer):
    class Meta:
        model = RideWithdrawal
        fields = [
            "id",
            "driver",
            "amount",
            "status",
            "reference",
            "failure_reason",
            "paid_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "driver",
            "status",
            "reference",
            "failure_reason",
            "paid_at",
            "created_at",
            "updated_at",
        ]