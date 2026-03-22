# senmi/models.py

from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    ROLE_CHOICES = (
        ('customer', 'Customer'),
        ('rider', 'Rider'),
    )

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return self.email


class RiderProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    full_name = models.CharField(max_length=255, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)

    profile_picture = models.ImageField(upload_to='riders/profile/', blank=True, null=True)
    rider_image_1 = models.ImageField(upload_to='riders/images1/', blank=True, null=True)
    rider_image_2 = models.ImageField(upload_to='riders/images2/', blank=True, null=True)

    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return self.user.email