import uuid
from django.contrib.auth import get_user_model
from django.contrib import admin
from django.conf import settings
from simple_history.admin import SimpleHistoryAdmin
from django.utils import timezone
from .models import FCMDevice, Notification, User, RiderProfile,Withdrawal
from .utils import send_email, send_fcm_notification
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import ValidationError
from .models import User,RiderWallet, Package, PackageTracking 


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
    fields = ('description', 'status', 'price', 'commission', 'rider')
    readonly_fields = ('description', 'status', 'price', 'commission', 'rider')
    extra = 0
    show_change_link = True
    ordering = ('-created_at',)

class PackageAsRiderInline(admin.TabularInline):
    model = Package
    fk_name = 'rider'  # Packages where user is the rider
    fields = ('description', 'status', 'price', 'commission', 'customer')
    readonly_fields = ('description', 'status', 'price', 'commission', 'customer')
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
        'is_staff',
        'is_active',
    )

    list_filter = ('role', 'is_staff', 'is_active')
    search_fields = ('username', 'email', 'user_id')
    ordering = ('-is_superuser', '-is_staff', 'id')
    readonly_fields = ('id', 'user_id')

    list_per_page = 50
    date_hierarchy = "date_joined"

    actions = [deactivate_users, activate_users]

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


# -----------------------------
# Customize RiderProfile admin
@admin.register(RiderProfile)
class RiderProfileAdmin(admin.ModelAdmin):
    list_display = ('rider_id', 'user', 'full_name', 'phone_number', 'status', 'rejection_reason')
    list_filter = ('status',)
    search_fields = ('user__email', 'full_name', 'phone_number')
    readonly_fields = ('id', 'rider_id')
    ordering = ('-created_at',)

    list_per_page = 50
    date_hierarchy = "created_at"

    def save_model(self, request, obj, form, change):
        # 0️⃣ Ensure rider_id exists
        if not obj.rider_id:
            obj.rider_id = f"RIDER-{uuid.uuid4().hex[:8].upper()}"

        # 1️⃣ Ensure required images are uploaded
        required_images = ['profile_picture', 'rider_image_1', 'rider_image_with_vehicle']
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
        'description',
        'status',
        'price',
        'commission',
        'is_paid',
        'created_at'
    )

    history_list_display = ["status", "rider", "is_paid"]

    list_filter = ('status', 'rider', 'is_paid')

    search_fields = (
        'package_id',
        'customer__email',
        'rider__email',
        'description'
    )

    list_editable = ('status',)
    list_per_page = 50
    date_hierarchy = 'created_at'

    readonly_fields = (
        'commission',
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

    # ---------------- SAFE REFUND ----------------
    @admin.action(description="Refund selected packages")
    def refund_packages(self, request, queryset):

        queryset = queryset.exclude(
            status="delivered"
        ).exclude(
            refund_status="refunded"
        )

        queryset.update(
            refund_status="refunded",
            refunded_at=timezone.now(),
            status="cancelled",
            is_paid=False,
            rider=None
        )

    # ---------------- SAVE ----------------
    def save_model(self, request, obj, form, change):

        if change:
            old_obj = Package.objects.get(pk=obj.pk)

            if old_obj.status in ["accepted", "picked_up"] and obj.status == "paid":
                obj.rider = None

        super().save_model(request, obj, form, change)

    # ---------------- ACTIONS ----------------

    def assign_random_rider(self, request, queryset):
        rider = User.objects.filter(role="rider", is_active=True).first()
        if rider:
            queryset.update(rider=rider, status="accepted")

    assign_random_rider.short_description = "Assign to available rider"

    def release_packages(self, request, queryset):
        queryset.update(rider=None, status="paid")

    release_packages.short_description = "Release packages back to pool"

    def force_delivered(self, request, queryset):
        queryset.update(status="delivered")

    force_delivered.short_description = "Force mark as delivered"

    def cancel_packages(self, request, queryset):
        queryset.update(status="cancelled", rider=None)

    cancel_packages.short_description = "Cancel selected packages"

    def mark_paid(self, request, queryset):
        queryset.update(is_paid=True)

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
    list_display = ('rider', 'balance', 'total_earned')
    search_fields = ('rider__email', 'rider__username')

@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):

    list_display = ("get_rider_id", "rider_email", "amount", "status", "created_at")

    list_filter = ("status",)
    search_fields = ("rider__email", "rider__riderprofile__rider_id", "bank_account")

    list_editable = ("status",)
    list_per_page = 50
    date_hierarchy = "created_at"

    actions = ["approve_withdrawals", "reject_withdrawals"]

    def approve_withdrawals(self, request, queryset):
        queryset.update(status="approved")

    def reject_withdrawals(self, request, queryset):
        queryset.update(status="rejected")

    def get_rider_id(self, obj):
        return obj.rider.riderprofile.rider_id

    def rider_email(self, obj):
        return obj.rider.email
    

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


