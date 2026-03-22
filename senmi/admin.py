from django.contrib import admin
from django.core.mail import send_mail
from django.conf import settings
from .models import User, RiderProfile

# -----------------------------
# Customize User admin
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'email', 'role', 'is_staff', 'is_active')
    list_filter = ('role', 'is_staff', 'is_active')
    search_fields = ('username', 'email')
    ordering = ('id',)
    readonly_fields = ('id',)


# -----------------------------
# Customize RiderProfile admin
@admin.register(RiderProfile)
class RiderProfileAdmin(admin.ModelAdmin):
    list_display = ('rider_id', 'user', 'full_name', 'phone_number', 'status', 'rejection_reason')
    list_filter = ('status',)
    search_fields = ('user__email', 'full_name', 'phone_number')
    readonly_fields = ('id', 'rider_id')
    ordering = ('id',)

    def save_model(self, request, obj, form, change):
        # 0️⃣ Ensure rider_id is set if missing
        if not obj.rider_id:
            import uuid
            obj.rider_id = f"RIDER-{uuid.uuid4().hex[:8].upper()}"

        # 1️⃣ Enforce all images uploaded
        required_images = ['profile_picture', 'rider_image_1', 'rider_image_with_bike']
        missing_images = [img for img in required_images if not getattr(obj, img)]
        if missing_images:
            raise ValueError(f"Cannot save: missing required images: {', '.join(missing_images)}")

        # --- Get old status before saving ---
        old_status = None
        if change:
            try:
                old_obj = RiderProfile.objects.get(pk=obj.pk)
                old_status = old_obj.status
            except RiderProfile.DoesNotExist:
                old_status = None

        # 2️⃣ Automatically set to pending only if first save (do NOT overwrite admin approval)
        if not change and not obj.status:
            obj.status = 'pending'

        # --- Save object ---
        super().save_model(request, obj, form, change)

        # 3️⃣ Send email to rider about submission (for new profiles or pending updates)
        if not change or obj.status == 'pending':
            send_mail(
                subject="Rider Profile Submitted",
                message=f"Hello {obj.user.username},\n\n"
                        f"Your rider profile (ID: {obj.rider_id}) has been submitted successfully "
                        "and is pending admin review.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[obj.user.email],
                fail_silently=True,
            )

        # 4️⃣ Send email to all admins about new pending profile
        from django.contrib.auth import get_user_model
        User = get_user_model()
        admins = User.objects.filter(is_superuser=True).values_list('email', flat=True)
        send_mail(
            subject="New Rider Profile Pending Review",
            message=f"Rider {obj.user.username} (ID: {obj.rider_id}) has submitted their profile. Please review and approve.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=admins,
            fail_silently=True,
        )

        # 5️⃣ Send email if status changed (approved/rejected)
        if change and old_status != obj.status:
            message = None
            if obj.status == 'approved':
                message = f"Hello {obj.user.username},\n\nYour rider profile (ID: {obj.rider_id}) has been approved! You can now start receiving orders."
            elif obj.status == 'rejected':
                message = f"Hello {obj.user.username},\n\nYour rider profile (ID: {obj.rider_id}) has been rejected. Reason: {obj.rejection_reason}"

            if message:  # Only send if message was set
                send_mail(
                    subject="Rider Profile Review",
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[obj.user.email],
                    fail_silently=True,
                )