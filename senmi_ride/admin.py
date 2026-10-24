from django.contrib import admin

from .models import (
    RideDriverProfile,
    RideDriverWallet,
    RideFCMDevice,
    RideNotification,
    RideNotificationRecipient,
    RideRequest,
    RideTracking,
    RideRating,
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

    list_filter = (
        "status",
        "is_online",
    )

    search_fields = (
        "driver_id",
        "full_name",
        "phone_number",
        "plate_number",
        "user__email",
    )

    readonly_fields = (
        "driver_id",
        "created_at",
    )

    actions = (
        "approve_drivers",
        "reject_drivers",
    )

    @admin.action(description="Approve selected drivers")
    def approve_drivers(self, request, queryset):
        queryset.update(
            status="approved",
            rejection_reason="",
            is_online=False,
        )

    @admin.action(description="Reject selected drivers")
    def reject_drivers(self, request, queryset):
        queryset.update(
            status="rejected",
            is_online=False,
        )


# ============================================================
# DRIVER WALLET
# ============================================================

@admin.register(RideDriverWallet)
class RideDriverWalletAdmin(admin.ModelAdmin):
    list_display = ("driver", "commission_balance", "total_commission_paid")

    search_fields = (
        "driver__email",
        "driver__username",
    )


# ============================================================
# RIDE REQUEST
# ============================================================

@admin.register(RideRequest)
class RideRequestAdmin(admin.ModelAdmin):

    list_display = (
        "ride_id",
        "passenger",
        "driver",
        "fare",
        "service_fee",
        "driver_earning",
        "payment_method",
        "payment_status",
        "status",
        "commission_paid",
        "created_at",
    )

    list_filter = (
        "status",
        "payment_method",
        "payment_status",
        "commission_paid",
    )

    search_fields = (
        "ride_id",
        "passenger__email",
        "driver__email",
        "pickup_address",
        "destination_address",
        "payment_reference",
    )

    readonly_fields = (
        "ride_id",
        "created_at",
        "updated_at",
        "completed_at",
        "cancelled_at",
        "payment_paid_at",
        "commission_paid_at",
    )


# ============================================================
# RIDE TRACKING
# ============================================================

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

    readonly_fields = (
        "timestamp",
    )


# ============================================================
# RIDE RATING
# ============================================================

@admin.register(RideRating)
class RideRatingAdmin(admin.ModelAdmin):

    list_display = (
        "ride",
        "passenger",
        "driver",
        "rating",
        "created_at",
    )

    list_filter = (
        "rating",
    )

    search_fields = (
        "ride__ride_id",
        "passenger__email",
        "driver__email",
    )

    readonly_fields = (
        "created_at",
    )


# ============================================================
# COMMISSION PAYMENT
# ============================================================

@admin.register(RideCommissionPayment)
class RideCommissionPaymentAdmin(admin.ModelAdmin):

    list_display = (
        "driver",
        "ride",
        "amount",
        "payment_method",
        "reference",
        "status",
        "paid_at",
        "created_at",
    )

    list_filter = (
        "status",
        "payment_method",
    )

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


# ============================================================
# COMMISSION TRANSACTION
# ============================================================

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

    readonly_fields = (
        "created_at",
    )


# ============================================================
# RIDE PRICING
# ============================================================

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

    list_filter = (
        "is_active",
    )

    search_fields = (
        "name",
    )

    readonly_fields = (
        "updated_at",
    )



class RideNotificationRecipientInline(admin.TabularInline):
    model = RideNotificationRecipient
    extra = 0
    can_delete = False
    readonly_fields = (
        "recipient",
        "is_read",
        "read_at",
    )
    fields = (
        "recipient",
        "is_read",
        "read_at",
    )


@admin.register(RideNotification)
class RideNotificationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "target",
        "sender",
        "created_at",
        "recipient_count",
    )

    list_filter = ("target", "created_at")
    search_fields = ("title", "message")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
    inlines = [RideNotificationRecipientInline]

    def recipient_count(self, obj):
        return obj.recipients.count()

    recipient_count.short_description = "Recipients"


@admin.register(RideNotificationRecipient)
class RideNotificationRecipientAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "notification",
        "recipient",
        "is_read",
        "read_at",
    )
    list_filter = ("is_read",)
    search_fields = (
        "notification__title",
        "recipient__username",
        "recipient__email",
    )
    list_select_related = ("notification", "recipient")

@admin.register(RideFCMDevice)
class RideFCMDeviceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "token_preview",
        "is_active",
        "created_at",
        "updated_at",
    )

    list_filter = ("is_active", "created_at")
    search_fields = ("user__username", "user__email", "token")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)

    @admin.display(description="FCM Token")
    def token_preview(self, obj):
        if len(obj.token) > 24:
            return f"{obj.token[:24]}..."
        return obj.token