# senmi/models.py
import random
from django.db.models import Q
from django.db import models
from django.conf import settings
from decimal import Decimal
from django.contrib.auth.models import AbstractUser
import uuid

class User(AbstractUser):
    ROLE_CHOICES = (
        ('customer', 'Customer'),
        ('rider', 'Rider'),
    )

    user_id = models.CharField(max_length=20, unique=True, editable=False, blank=True)

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    phone_number = models.CharField(max_length=20, blank=True) 

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def save(self, *args, **kwargs):
        if not self.user_id:
            self.user_id = f"SENMI-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

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
    profile_picture = models.ImageField(upload_to='riders_profile/', blank=True, null=True)
    rider_image_1 = models.ImageField(upload_to='riders_images1/', blank=True, null=True)
    rider_image_with_vehicle = models.ImageField(upload_to='riders_vehicle_images2/', blank=True, null=True)
    vehicle_number = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    rating = models.FloatField(default=0)
    rating_count = models.IntegerField(default=0) 
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
    



#Customer(vendor)package order
class Package(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('picked_up', 'Picked Up'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]

    PAYMENT_TYPE_CHOICES = [
        ('sender', 'Sender Pays'),
        ('receiver', 'Receiver Pays'),
    ]

    payment_type = models.CharField(
        max_length=10,
        choices=PAYMENT_TYPE_CHOICES,
        default='sender'
    )

    is_collected = models.BooleanField(default=False)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')
    rider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='deliveries')

    description = models.CharField(max_length=255)

    pickup_address = models.TextField()
    delivery_address = models.TextField()
    package_id = models.CharField(max_length=20, unique=True, blank=True)
    pickup_lat = models.FloatField(null=True, blank=True)
    pickup_lng = models.FloatField(null=True, blank=True)
    delivery_lat = models.FloatField(null=True, blank=True)
    delivery_lng = models.FloatField(null=True, blank=True)

    receiver_name = models.CharField(max_length=255, blank=True)
    receiver_phone = models.CharField(max_length=20, blank=True)

    price = models.DecimalField(max_digits=10, decimal_places=2)
    commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rider_earning = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_reference = models.CharField(max_length=100, blank=True, null=True)
    is_paid = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    delivery_code = models.CharField(max_length=4, blank=True, null=True)  # NEW

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        #package unique id
        if not self.package_id:
            self.package_id = f"PKG-{uuid.uuid4().hex[:8].upper()}"

        # Generate 4-digit code if not already set
        if not self.delivery_code:
            self.delivery_code = f"{random.randint(1000, 9999)}"

        base_fee = Decimal('200')
        percentage = Decimal('0.10')

        self.commission = base_fee + (self.price * percentage)
        self.rider_earning = self.price - self.commission
        super().save(*args, **kwargs)



class PackageTracking(models.Model):
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name='tracking_entries')
    rider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    latitude = models.FloatField()
    longitude = models.FloatField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"Tracking: {self.package.package_id} by {self.rider.username} at {self.timestamp}"
    

    
class RiderWallet(models.Model):
    rider = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_earned = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def deposit(self, amount):
        self.balance += amount
        self.total_earned += amount
        self.save()

    def withdraw(self, amount):
        if amount > self.balance:
            raise ValueError("Insufficient funds")  # 🚫 prevents overdraft
        self.balance -= amount
        self.save()



class RiderRating(models.Model):
    rider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ratings')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    package = models.OneToOneField(Package, on_delete=models.CASCADE)

    rating = models.IntegerField()  # 1–5 stars
    comment = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)


class PackageStatusHistory(models.Model):
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name='history')
    status = models.CharField(max_length=20)
    timestamp = models.DateTimeField(auto_now_add=True)