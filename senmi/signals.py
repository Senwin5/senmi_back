
import logging

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import send_mail

from .models import User, RiderProfile, RideDriverProfile

logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def create_rider_profile(sender, instance, created, **kwargs):
    if created and instance.role == "rider":
        RiderProfile.objects.get_or_create(
            user=instance,
            defaults={"status": "pending"},
        )


@receiver(post_save, sender=RideDriverProfile)
def notify_admin_driver_profile_submitted(
    sender, instance, created, **kwargs
):
    if not created:
        return

    try:
        subject = "New Ride Driver Profile Submitted"

        message = (
            "A ride driver has submitted a profile for approval.\n\n"
            f"Driver ID: {instance.driver_id}\n"
            f"Name: {instance.full_name}\n"
            f"Email: {instance.user.email}\n"
            f"Phone: {instance.phone_number}\n"
            f"Vehicle: {instance.vehicle_brand} {instance.vehicle_model}\n"
            f"Plate Number: {instance.plate_number}\n"
            f"Status: {instance.get_status_display()}\n\n"
            "Please review the profile in the admin dashboard."
        )

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.NOTIFY_EMAIL],
            fail_silently=False,
        )

    except Exception:
        logger.exception(
            "Failed to send ride driver profile notification: %s",
            instance.driver_id,
        )
