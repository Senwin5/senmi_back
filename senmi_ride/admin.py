from django.contrib import admin
from .models import (
    RideDriverProfile,
    RideDriverWallet,
    RideRequest,
    RideTracking,
    RideRating,
    RideWithdrawal,
    RideBank,
    RideCommissionPayment,
    RideCommissionTransaction,
    RidePricingConfig,
)


@admin.register(RideDriverProfile)
class RideDriverProfileAdmin(admin.ModelAdmin):
    list_display = (
        "driver_id",
        "full_name",
        "phone_number",
        "vehicle_brand",
        "vehicle_model",
        "plate_number",
        "status",
        "is_online",
        "rating",
        "created_at",
    )
    list_filter = ("status", "is_online")
    search_fields = (
        "driver_id",
        "full_name",
        "phone_number",
        "plate_number",
        "user__email",
    )
    readonly_fields = ("driver_id", "created_at")


@admin.register(RideDriverWallet)
class RideDriverWalletAdmin(admin.ModelAdmin):
    list_display = (
        "driver",
        "balance",
        "total_commission_paid",
    )
    search_fields = (
        "driver__email",
        "driver__username",
    )


@admin.register(RideRequest)
class RideRequestAdmin(admin.ModelAdmin):
    list_display = (
        "ride_id",
        "passenger",
        "driver",
        "fare",
        "payment_method",
        "status",
        "commission_paid",
        "created_at",
    )
    list_filter = (
        "status",
        "payment_method",
        "commission_paid",
    )
    search_fields = (
        "ride_id",
        "passenger__email",
        "driver__email",
        "pickup_address",
        "destination_address",
    )
    readonly_fields = (
        "ride_id",
        "created_at",
        "updated_at",
        "completed_at",
        "cancelled_at",
    )


@admin.register(RideTracking)
class RideTrackingAdmin(admin.ModelAdmin):
    list_display = (
        "ride",
        "driver",
        "latitude",
        "longitude",
        "timestamp",
    )
    search_fields = (
        "ride__ride_id",
        "driver__email",
    )
    readonly_fields = ("timestamp",)


@admin.register(RideRating)
class RideRatingAdmin(admin.ModelAdmin):
    list_display = (
        "ride",
        "passenger",
        "driver",
        "rating",
        "created_at",
    )
    list_filter = ("rating",)
    search_fields = (
        "ride__ride_id",
        "passenger__email",
        "driver__email",
    )


@admin.register(RideWithdrawal)
class RideWithdrawalAdmin(admin.ModelAdmin):
    list_display = (
        "driver",
        "amount",
        "status",
        "reference",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = (
        "driver__email",
        "reference",
    )


@admin.register(RideBank)
class RideBankAdmin(admin.ModelAdmin):
    list_display = (
        "driver",
        "account_name",
        "account_number",
        "bank_name",
        "bank_code",
    )
    search_fields = (
        "driver__email",
        "account_name",
        "account_number",
        "bank_name",
    )


@admin.register(RideCommissionPayment)
class RideCommissionPaymentAdmin(admin.ModelAdmin):
    list_display = (
        "driver",
        "ride",
        "amount",
        "reference",
        "status",
        "paid_at",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = (
        "driver__email",
        "reference",
        "ride__ride_id",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "paid_at",
    )


@admin.register(RideCommissionTransaction)
class RideCommissionTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "driver",
        "payment",
        "amount",
        "reference",
        "created_at",
    )
    search_fields = (
        "driver__email",
        "reference",
        "payment__reference",
    )
    readonly_fields = ("created_at",)


@admin.register(RidePricingConfig)
class RidePricingConfigAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "base_fare",
        "per_km_rate",
        "per_minute_rate",
        "service_fee_percentage",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active",)