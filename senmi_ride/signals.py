from django.db.models.signals import post_save
from django.dispatch import receiver

from senmi.models import User
from .models import RideDriverProfile


@receiver(post_save, sender=User)
def create_ride_driver_profile(sender, instance, created, **kwargs):

    if created and instance.role == "ride_driver":

        RideDriverProfile.objects.get_or_create(
            user=instance,
            defaults={
                "full_name": instance.username,
                "phone_number": instance.phone_number or "",
                "vehicle_brand": "",
                "vehicle_model": "",
                "plate_number": f"TEMP-{instance.id}",
                "status": "pending",
            }
        )