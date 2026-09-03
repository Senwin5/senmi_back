import uuid
from django.contrib.auth import get_user_model
from django.contrib import admin
from django.conf import settings
from django.db import transaction
from simple_history.admin import SimpleHistoryAdmin
from django.utils import timezone
from django.contrib import admin
from django.utils.html import format_html
from .models import WalletTransaction
from .models import FCMDevice, Notification, User, RiderProfile,Withdrawal, PricingConfig
from .utils import notify_admin_dashboard, send_email, send_fcm_notification
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import ValidationError
from .models import User,RiderWallet, Package, PackageTracking,PasswordResetOTP


@admin.action(description="Deactivate selected users")
def deactivate_users(modeladmin, request, queryset):
    queryset.update(is_active=False)


@admin.action(description="Activate selected users")
def activate_users(modeladmin, request, queryset):
    queryset.update(is_active=True)

# -----------------------------
# Inlines for User admin

class RiderWalletInline(admin.StackedInline):
    model = RiderWallet
    can_delete = False
    readonly_fields = ('balance', 'total_earned')
    extra = 0

class PackageInline(admin.TabularInline):
    model = Package
    fk_name = 'customer'  # Packages where user is the customer
    fields = ( 'status', 'price', 'service_fee', 'rider')
    readonly_fields = ('status', 'price', 'service_fee', 'rider')
    extra = 0
    show_change_link = True
    ordering = ('-created_at',)

class PackageAsRiderInline(admin.TabularInline):
    model = Package
    fk_name = 'rider'  # Packages where user is the rider
    fields = ( 'status', 'price', 'service_fee', 'customer')
    readonly_fields = ( 'status', 'price', 'service_fee', 'customer')
    extra = 0
    show_change_link = True
    ordering = ('-created_at',)

class PackageTrackingInline(admin.TabularInline):
    model = PackageTracking
    fields = ('package', 'latitude', 'longitude', 'timestamp')
    readonly_fields = ('package', 'latitude', 'longitude', 'timestamp')
    extra = 0
    show_change_link = True
    ordering = ('-timestamp',)




# Customize User admin
@admin.register(User)
class UserAdmin(BaseUserAdmin):

    list_display = (
        'user_id',
        'email',
        'username',
        'role',
        'account_status',
        'is_staff',
    )

    list_filter = (
        'role',
        'is_staff',
        'is_active',
    )

    search_fields = (
        'username',
        'email',
        'user_id',
    )

    ordering = ('-is_superuser', '-is_staff', 'id')
    readonly_fields = ('id', 'user_id')

    list_per_page = 50
    date_hierarchy = "date_joined"

    actions = [deactivate_users, activate_users]

    def account_status(self, obj):
        if obj.is_active:
            return "Active"

        return "Deactivated"

    account_status.short_description = "Account Status"

    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Senmi",
            {
                "fields": (
                    "user_id",
                    "role",
                    "phone_number",
                )
            },
        ),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (
            None,
            {
                "fields": (
                    "email",
                    "username",
                    "role",
                    "phone_number",
                )
            },
        ),
    )

    inlines = [
        RiderWalletInline,
        PackageInline,
        PackageAsRiderInline,
        PackageTrackingInline,
    ]


@admin.register(PasswordResetOTP)
class PasswordResetOTPAdmin(admin.ModelAdmin):
    list_display = ('user', 'otp','created_at')
    ordering = ('-created_at',)



# -----------------------------
# Customize RiderProfile admin
@admin.register(RiderProfile)
class RiderProfileAdmin(admin.ModelAdmin):
    list_display = ('rider_id','user','full_name','phone_number','status','account_status')
    list_filter = ('status','user__is_active')
    search_fields = ('user__email', 'full_name', 'phone_number')
    readonly_fields = ('id', 'rider_id')
    ordering = ('-created_at',)

    list_per_page = 50
    date_hierarchy = "created_at"
    @admin.display(description="Account Status")
    def account_status(self, obj):
        if obj.user.is_active:
            return "Active"

        return "Deactivated"

    def save_model(self, request, obj, form, change):
        # 0️⃣ Ensure rider_id exists
        if not obj.rider_id:
            obj.rider_id = f"RIDER-{uuid.uuid4().hex[:8].upper()}"

        # 1️⃣ Ensure required images are uploaded
        required_images = ['profile_picture', 'nin_image', 'rider_image_with_vehicle']
        missing_images = [img for img in required_images if not getattr(obj, img)]
        if missing_images:
            #raise ValueError(f"Cannot save: missing required images: {', '.join(missing_images)}")
            raise ValidationError(
                f"Missing required images: {', '.join(missing_images)}"
            )
        

        # 2️⃣ Track old status to detect changes
        old_status = None
        if change:
            try:
                old_status = RiderProfile.objects.get(pk=obj.pk).status
            except RiderProfile.DoesNotExist:
                old_status = None

        # 3️⃣ Default new profiles to 'pending' if no status
        if not change and not obj.status:
            obj.status = 'pending'

        # 4️⃣ Save the object
        super().save_model(request, obj, form, change)

        if not change or obj.status == 'pending':

            send_fcm_notification(
                obj.user,
                "Rider Pending",
                "Your rider application is under review",
                {"type": "rider_pending"}
            )
            send_email(
                subject="Your Rider Profile Successfully Submitted",
                message = (
                    f"Hello {obj.user.username},\n\n"
                    "Thank you for submitting your rider profile for Senmi.\n\n"
                    "Your application has been received and is now under review.\n\n"
                    f"Rider Profile ID: {obj.rider_id}\n\n"
                    "What happens next:\n"
                    "• Our team will review your details and documents\n"
                    "• We will verify your information for safety and quality\n"
                    "• You will receive an update once review is complete\n\n"
                    "Please note:\n"
                    "Review time may vary depending on application volume.\n\n"
                    "Thank you for joining Senmi.\n"
                    "We look forward to having you as a rider.\n\n"
                    "Best regards,\n"
                    "Senmi Rider Team"
                ),
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[obj.user.email],
                fail_silently=False,
            )

        # Notify admins
        # Notify admins only for new applications
        if not change:

            UserModel = get_user_model()

            admins = list(
                UserModel.objects.filter(is_superuser=True)
                .values_list('email', flat=True)
            )

            send_email(
                subject="New Rider Profile Awaiting Review",
                message=(
                    "Hello Admin Team,\n\n"
                    "A new rider profile has been submitted for review.\n\n"
                    f"Username: {obj.user.username}\n"
                    f"Profile ID: {obj.rider_id}\n\n"
                    "Please review from admin dashboard.\n\n"
                    "Regards,\n"
                    "Senmi System"
                ),
                from_email=settings.EMAIL_HOST_USER,
                
                recipient_list=["senmisupport@gmail.com"],
                fail_silently=False,
            )


        # 7️⃣ Notify rider if status changed (approved/rejected)
        if change and old_status != obj.status:
            message = None

            if obj.status == 'approved':
      
                send_fcm_notification(
                    obj.user,
                    "Rider Approved",
                    "Your rider account has been approved",
                    {
                        "type": "rider_approved"
                    }
                )
                
                message = f"""
        Hello {obj.user.username},

        Your rider profile (ID: {obj.rider_id}) has been approved by Senmi team.

        Kindly follow the Terms and Conditions of the app.

        You can now start accepting deliveries using the Senmi app.

        Best regards,
        Senmi Team
        """

            elif obj.status == 'rejected':

                send_fcm_notification(
                    obj.user,
                    "Rider Rejected",
                    obj.rejection_reason or "Your rider application was rejected",
                    {
                        "type": "rider_rejected"
                    }
                )
                message = (
                    f"Hello {obj.user.username},\n\n"
                    "We regret to inform you that your rider profile was not approved.\n\n"
                    f"Rider ID: {obj.rider_id}\n\n"
                    "Reason:\n"
                    f"{obj.rejection_reason}\n\n"
                    "Please review and update your information if needed.\n\n"
                    "Best regards,\n"
                    "Senmi Team"
                )

            if message:
                send_email(
                    subject="Rider Profile Review",
                    message=message,
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[obj.user.email],
                    fail_silently=False,
                )



# -----------------------------
# Package, RiderWallet, PackageTracking, admins
@admin.register(Package)
class PackageAdmin(SimpleHistoryAdmin):

    list_display = (
        'package_id',
        'customer',
        'rider',
        #'description',
        'status',
        'price',
        'service_fee',
        'is_paid',
        'created_at'
    )

    history_list_display = ["status", "rider", "is_paid"]

    list_filter = ('status', 'rider', 'is_paid')

    search_fields = (
        'package_id',
        'customer__email',
        'rider__email',
        #'description'
    )

    list_editable = ('status',)
    list_per_page = 50
    date_hierarchy = 'created_at'

    readonly_fields = (
        'service_fee',
        'created_at',
        'updated_at'
    )

    ordering = ('-created_at',)

    actions = [
        'assign_random_rider',
        'release_packages',
        'force_delivered',
        'cancel_packages',
        'mark_paid',
        'refund_packages'
    ]

    @admin.action(description="Refund selected packages")
    def refund_packages(self, request, queryset):

        queryset = queryset.exclude(
            status="delivered"
        ).exclude(
            refund_status="refunded"
        )

        for package in queryset:
            package.refund_status = "refunded"
            package.refunded_at = timezone.now()
            package.status = "cancelled"
            package.is_paid = False
            package.rider = None
            package.save()

    def save_model(self, request, obj, form, change):

        if change:
            old_obj = Package.objects.get(pk=obj.pk)

            if old_obj.status in ["accepted", "picked_up"] and obj.status == "paid":
                obj.rider = None

        super().save_model(request, obj, form, change)

    def assign_random_rider(self, request, queryset):
        rider = User.objects.filter(
            role="rider",
            is_active=True
        ).first()

        if rider:
            for package in queryset:
                package.rider = rider
                package.status = "accepted"
                package.save()

    assign_random_rider.short_description = "Assign to available rider"

    def release_packages(self, request, queryset):
        for package in queryset:
            package.rider = None
            package.status = "paid"
            package.save()

    release_packages.short_description = "Release packages back to pool"


    def force_delivered(self, request, queryset):
        for package in queryset:
            package.status = "delivered"

            if not package.delivered_at:
                package.delivered_at = timezone.now()

            package.save()

    force_delivered.short_description = "Force mark as delivered"

    def cancel_packages(self, request, queryset):
        for package in queryset:
            package.status = "cancelled"
            package.rider = None
            package.save()

    cancel_packages.short_description = "Cancel selected packages"

    def mark_paid(self, request, queryset):
        for package in queryset:
            package.is_paid = True
            package.save()

    mark_paid.short_description = "Mark as paid"



HistoricalPackage = Package.history.model
@admin.register(HistoricalPackage)
class HistoricalPackageAdmin(admin.ModelAdmin):
    list_display = (
        "package_id",
        "status",
        "history_type",
        "history_date",
        "history_user",
    )

    ordering = ("-history_date",)



@admin.register(PackageTracking)
class PackageTrackingAdmin(admin.ModelAdmin):
    list_display = ('package', 'rider', 'latitude', 'longitude', 'timestamp')
    search_fields = ('package__description', 'rider__email')
    ordering = ('-timestamp',)



@admin.register(RiderWallet)
class RiderWalletAdmin(admin.ModelAdmin):

    list_display = (
        "display_rider_id",
        "rider",
        "balance",
        "total_earned",
    )

    search_fields = (
        "rider__email",
        "rider__username",
        "rider__riderprofile__rider_id",
        "rider__riderprofile__full_name",
    )

    list_per_page = 50

    @admin.display(description="Rider ID", ordering="rider__riderprofile__rider_id")
    def display_rider_id(self, obj):
        try:
            return obj.rider.riderprofile.rider_id
        except RiderProfile.DoesNotExist:
            return "—"
        

@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):

    list_display = (
        "get_rider_id",
        "rider_full_name",
        "rider_email",
        "account_name",
        "bank_account",
        "bank_code",
        "amount",
        "identity_check",
        "status",
        "reference",
        "created_at",
    )

    list_filter = (
        "status",
        "created_at",
    )

    search_fields = (
        "rider__email",
        "rider__riderprofile__rider_id",
        "bank_account",
        "account_name",
        "reference",
    )

    readonly_fields = (
        "rider",
        "amount",
        "bank_account",
        "bank_code",
        "account_name",
        "reference",
        "failure_reason",
        "created_at",
        "paid_at",
    )

    list_per_page = 50

    date_hierarchy = "created_at"

    actions = [
        "approve_withdrawals",
        "reject_withdrawals",
        "mark_withdrawals_paid",
    ]

    # =====================================================
    # APPROVE
    # =====================================================

    @admin.action(
        description="Approve selected withdrawals"
    )
    def approve_withdrawals(self, request, queryset):

        for withdrawal in queryset:

            if withdrawal.status != "pending":

                self.message_user(
                    request,
                    (
                        f"Withdrawal #{withdrawal.id} "
                        f"cannot be approved because "
                        f"it is {withdrawal.status}."
                    ),
                    level="ERROR",
                )
                continue

            with transaction.atomic():

                locked = (
                    Withdrawal.objects
                    .select_for_update()
                    .select_related("rider")
                    .get(id=withdrawal.id)
                )

                # Re-check after locking
                if locked.status != "pending":
                    continue

                locked.status = "approved"

                locked.save(
                    update_fields=[
                        "status",
                    ]
                )

            send_fcm_notification(
                locked.rider,
                "Withdrawal Approved",
                (
                    f"Your withdrawal of "
                    f"₦{locked.amount:,.2f} "
                    "has been approved and is "
                    "being processed."
                ),
                {
                    "type": "withdrawal_approved",
                    "withdrawal_id": locked.id,
                },
            )

            self.message_user(
                request,
                (
                    f"Withdrawal #{locked.id} "
                    "approved successfully."
                ),
            )

        notify_admin_dashboard()

    # =====================================================
    # REJECT
    # =====================================================

    @admin.action(
        description="Reject selected withdrawals"
    )
    def reject_withdrawals(self, request, queryset):

        for withdrawal in queryset:

            if withdrawal.status != "pending":

                self.message_user(
                    request,
                    (
                        f"Withdrawal #{withdrawal.id} "
                        f"cannot be rejected because "
                        f"it is {withdrawal.status}."
                    ),
                    level="ERROR",
                )
                continue

            with transaction.atomic():

                locked = (
                    Withdrawal.objects
                    .select_for_update()
                    .select_related("rider")
                    .get(id=withdrawal.id)
                )

                # Re-check after locking
                if locked.status != "pending":
                    continue

                wallet = (
                    RiderWallet.objects
                    .select_for_update()
                    .get_or_create(
                        rider=locked.rider
                    )[0]
                )

                # -----------------------------------------
                # RETURN RESERVED MONEY
                # -----------------------------------------

                wallet.balance += locked.amount

                wallet.save(
                    update_fields=[
                        "balance",
                    ]
                )

                # -----------------------------------------
                # RECORD WALLET REFUND
                # -----------------------------------------

                WalletTransaction.objects.create(
                    rider=locked.rider,
                    amount=locked.amount,
                    transaction_type="credit",
                    description=(
                        f"Refund for rejected "
                        f"withdrawal #{locked.id}"
                    ),
                )

                # -----------------------------------------
                # MARK REJECTED
                # -----------------------------------------

                locked.status = "rejected"

                locked.failure_reason = (
                    "Rejected by admin"
                )

                locked.save(
                    update_fields=[
                        "status",
                        "failure_reason",
                    ]
                )

            send_fcm_notification(
                locked.rider,
                "Withdrawal Rejected",
                (
                    f"Your ₦{locked.amount:,.2f} "
                    "withdrawal was rejected. "
                    "The money has been returned "
                    "to your wallet."
                ),
                {
                    "type": "withdrawal_rejected",
                    "withdrawal_id": locked.id,
                },
            )

            self.message_user(
                request,
                (
                    f"Withdrawal #{locked.id} "
                    "rejected and money returned."
                ),
            )

        notify_admin_dashboard()

    # =====================================================
    # MARK AS PAID
    # =====================================================

    @admin.action(
        description="Mark selected withdrawals as paid"
    )
    def mark_withdrawals_paid(self, request, queryset):

        for withdrawal in queryset:

            if withdrawal.status != "approved":

                self.message_user(
                    request,
                    (
                        f"Withdrawal #{withdrawal.id} "
                        f"cannot be marked as paid because "
                        f"it is {withdrawal.status}."
                    ),
                    level="ERROR",
                )
                continue

            with transaction.atomic():

                locked = (
                    Withdrawal.objects
                    .select_for_update()
                    .select_related("rider")
                    .get(id=withdrawal.id)
                )

                # Re-check after locking
                if locked.status != "approved":
                    continue

                locked.status = "success"
                locked.paid_at = timezone.now()

                locked.save(
                    update_fields=[
                        "status",
                        "paid_at",
                    ]
                )

            send_fcm_notification(
                locked.rider,
                "Withdrawal Successful",
                (
                    f"Your withdrawal of "
                    f"₦{locked.amount:,.2f} "
                    "has been paid successfully."
                ),
                {
                    "type": "withdrawal_success",
                    "withdrawal_id": locked.id,
                },
            )

            self.message_user(
                request,
                (
                    f"Withdrawal #{locked.id} "
                    "marked as paid."
                ),
            )

        notify_admin_dashboard()

    # =====================================================
    # DISPLAY HELPERS
    # =====================================================

    @admin.display(description="Rider ID")
    def get_rider_id(self, obj):

        try:
            return obj.rider.riderprofile.rider_id

        except RiderProfile.DoesNotExist:
            return "—"

    @admin.display(description="Rider Email")
    def rider_email(self, obj):
        return obj.rider.email

    @admin.display(description="Identity Check")
    def identity_check(self, obj):

        try:

            rider_name = (
                obj.rider.riderprofile.full_name or ""
            ).strip().lower()

            account_name = (
                obj.account_name or ""
            ).strip().lower()

            if not rider_name or not account_name:

                return format_html(
                    '<span style="color:orange;font-weight:bold;">{}</span>',
                    "CHECK",
                )

            if rider_name == account_name:

                return format_html(
                    '<span style="color:green;font-weight:bold;">{}</span>',
                    "✓ MATCH",
                )

            return format_html(
                '<span style="color:red;font-weight:bold;">{}</span>',
                "⚠ NAME MISMATCH",
            )

        except RiderProfile.DoesNotExist:

            return format_html(
                '<span style="color:red;font-weight:bold;">{}</span>',
                "NO RIDER PROFILE",
            )
        
        
        
@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):

    list_display = ("rider_id","rider","package","colored_type","amount","description","created_at",)
    list_filter = ("transaction_type","created_at",)
    search_fields = ("rider__username","rider__email","rider__riderprofile__rider_id","package__package_id",)
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
    list_per_page = 25

    @admin.display(description="Rider ID")
    def rider_id(self, obj):
        if hasattr(obj.rider, "riderprofile"):
            return obj.rider.riderprofile.rider_id

        return "—"

    @admin.display(description="Type")
    def colored_type(self, obj):
        if obj.transaction_type == "credit":
            return format_html(
                '<span style="color:green;font-weight:bold;">{}</span>',
                "CREDIT",
            )

        return format_html(
            '<span style="color:red;font-weight:bold;">{}</span>',
            "DEBIT",
        )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'type', 'is_read', 'created_at')
    list_filter = ('is_read', 'type')
    search_fields = ('user__email', 'message')
    ordering = ('-created_at',)


@admin.register(FCMDevice)
class FCMDeviceAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "device_type",
        "is_active",
        "created_at",
    )

    search_fields = (
        "user__email",
        "token",
    )

    list_filter = (
        "device_type",
        "is_active",
    )


@admin.register(PricingConfig)
class PricingConfigAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "base_fee",
        "per_km_rate",
        "fuel_multiplier",
        "is_active",
        "updated_at",
    )

    list_editable = ("base_fee", "per_km_rate", "fuel_multiplier", "is_active")