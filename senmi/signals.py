from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User, RiderProfile

@receiver(post_save, sender=User)
def create_rider_profile(sender, instance, created, **kwargs):
    if created and instance.role == 'rider':
        RiderProfile.objects.create(user=instance)