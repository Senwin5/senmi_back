# senmi/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings
import uuid


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
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    
    # Unique Rider Tracking ID
    rider_id = models.CharField(max_length=20, unique=True, blank=True, editable=False)

    # Profile fields
    full_name = models.CharField(max_length=255, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    profile_picture = models.ImageField(upload_to='riders/profile/', blank=True, null=True)
    rider_image_1 = models.ImageField(upload_to='riders/images1/', blank=True, null=True)
    rider_image_with_bike = models.ImageField(upload_to='riders/images2/', blank=True, null=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)

    # Status fields
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    rejection_reason = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        # Generate a unique rider ID if it doesn't exist
        if not self.rider_id:
            self.rider_id = f"RIDER-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.status}"
    




class Package(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),      # Waiting for rider to accept
        ('accepted', 'Accepted'),    # Rider accepted the package
        ('picked_up', 'Picked Up'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')
    rider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='deliveries')
    description = models.CharField(max_length=255)
    pickup_address = models.TextField()
    delivery_address = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)        # Total price customer pays
    commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # Your app’s cut
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Auto-calculate commission: e.g., 500 naira fixed per package
        self.commission = 500
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Package {self.id} - {self.status}"