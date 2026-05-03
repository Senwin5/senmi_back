import uuid
from django.contrib.auth import get_user_model
from django.contrib import admin
from django.core.mail import send_mail
from django.conf import settings
from .models import User, RiderProfile
from .models import RiderWallet, Package, PackageTracking, PackageStatusHistory

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

# -----------------------------
# Customize User admin

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('user_id', 'username', 'email', 'role', 'is_staff', 'is_active')
    list_filter = ('role', 'is_staff', 'is_active')
    search_fields = ('username', 'email', 'user_id')
    ordering = ('id',)
    readonly_fields = ('id', 'user_id')

    inlines = [RiderWalletInline, PackageInline, PackageAsRiderInline, PackageTrackingInline]

# -----------------------------
# Customize RiderProfile admin


@admin.register(RiderProfile)
class RiderProfileAdmin(admin.ModelAdmin):
    list_display = ('rider_id', 'user', 'full_name', 'phone_number', 'status', 'rejection_reason')
    list_filter = ('status',)
    search_fields = ('user__email', 'full_name', 'phone_number')
    readonly_fields = ('id', 'rider_id')
    ordering = ('-created_at',)

    def save_model(self, request, obj, form, change):
        # 0️⃣ Ensure rider_id exists
        if not obj.rider_id:
            obj.rider_id = f"RIDER-{uuid.uuid4().hex[:8].upper()}"

        # 1️⃣ Ensure required images are uploaded
        required_images = ['profile_picture', 'rider_image_1', 'rider_image_with_vehicle']
        missing_images = [img for img in required_images if not getattr(obj, img)]
        if missing_images:
            raise ValueError(f"Cannot save: missing required images: {', '.join(missing_images)}")

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

        # 5️⃣ Notify the rider on new submission or pending updates
        '''if not change or obj.status == 'pending':
            send_mail(
                subject="Rider Profile Submitted",
                message=f"Hello {obj.user.username},\n\n"
                        f"Your rider profile (ID: {obj.rider_id}) has been submitted and is pending review.",
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[obj.user.email],
                fail_silently=False,
            )

        # 6️⃣ Notify all admins about new pending profile
        UserModel = get_user_model()
        admins = list(UserModel.objects.filter(is_superuser=True).values_list('email', flat=True))
        send_mail(
            subject="New Rider Profile Pending Review",
            message=f"Hello team. Rider {obj.user.username} (ID: {obj.rider_id}) has submitted their profile. Please review.",
            from_email=settings.EMAIL_HOST_USER,
            recipient_list= ["senmilog@gmail.com"],  # now admins is a list
            fail_silently=False,
        )'''


        if not change or obj.status == 'pending':
            send_mail(
                subject="Your Rider Profile Has Been Successfully Submitted",
                message=f"""
        Hello {obj.user.username},

        Thank you for completing and submitting your rider profile for Senmi.

        We are pleased to inform you that your application has been successfully received and is now under review by our verification team.

        Your Rider Profile ID: {obj.rider_id}

        What happens next?
        • Our team will carefully review the information and documents you submitted.
        • This process helps us ensure the safety, reliability, and quality of our delivery network.
        • Once the review is complete, you will receive another email notifying you whether your profile has been approved or if additional updates are required.

        Please note:
        Approval times may vary depending on application volume and verification requirements.

        We appreciate your patience during this process.

        Thank you for choosing to partner with Senmi and for taking the first step toward becoming part of our trusted rider community.

        We look forward to having you deliver with us soon.

        Best regards,
        Senmi Rider Verification Team
        """,
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[obj.user.email],
                fail_silently=False,
            )

        # Notify admins
        UserModel = get_user_model()
        admins = list(
            UserModel.objects.filter(is_superuser=True)
            .values_list('email', flat=True)
        )

        send_mail(
            subject="New Rider Profile Awaiting Review",
            message=f"""
        Hello Admin Team,

        A new rider profile has just been submitted and is currently awaiting review.

        Rider Details
        Username: {obj.user.username}
        Profile ID: {obj.rider_id}
        Current Status: Pending Review

        Please log in to the admin dashboard to verify the submitted information and take the appropriate action.

        Timely review helps maintain an efficient onboarding experience for new riders.

        Regards,
        Senmi Automated Notification System
        """,
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=["senmilog@gmail.com"],
            fail_silently=False,
        )





        # 7️⃣ Notify rider if status changed (approved/rejected)
        if change and old_status != obj.status:
            message = None

            if obj.status == 'approved':
                message = f"""
        Hello {obj.user.username},

        Your rider profile (ID: {obj.rider_id}) has been approved by Senmi team.

        Kindly follow the Terms and Conditions of the app.

        You can now start accepting deliveries using the Senmi app.

        Best regards,
        Senmi Team
        """

            elif obj.status == 'rejected':
                message = f"""
        Hello {obj.user.username},

        Your rider profile (ID: {obj.rider_id}) has been rejected.

        Reason:
        {obj.rejection_reason}

        Please review and update your details.

        Best regards,
        Senmi Team
        """

            if message:
                send_mail(
                    subject="Rider Profile Review",
                    message=message,
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[obj.user.email],
                    fail_silently=False,
                )



# -----------------------------
# Package, RiderWallet, PackageTracking, PackageStatusHistory admins
@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ('package_id', 'customer', 'rider', 'description', 'status', 'price', 'commission','is_paid', 'created_at')
    list_filter = ('status', 'rider')
    search_fields = ('customer__email', 'rider__email', 'description')
    readonly_fields = ('commission', 'created_at', 'updated_at')
    ordering = ('-created_at',)

@admin.register(RiderWallet)
class RiderWalletAdmin(admin.ModelAdmin):
    list_display = ('rider', 'balance', 'total_earned')
    search_fields = ('rider__email', 'rider__username')

@admin.register(PackageTracking)
class PackageTrackingAdmin(admin.ModelAdmin):
    list_display = ('package', 'rider', 'latitude', 'longitude', 'timestamp')
    search_fields = ('package__description', 'rider__email')
    ordering = ('-timestamp',)

@admin.register(PackageStatusHistory)
class PackageStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('package','timestamp')
    ordering = ('-timestamp',)