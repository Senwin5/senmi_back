# senmi/models.py
import random
from django.db.models import Q
from django.db import models
from django.conf import settings
from decimal import Decimal
from django.contrib.auth.models import AbstractUser
import uuid
from io import BytesIO
from PIL import Image
from cloudinary.models import CloudinaryField
from django.core.files.uploadedfile import InMemoryUploadedFile
import sys


def compress_image(image, max_size=(1024, 1024), quality=70):
    try:
        img = Image.open(image)

        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        img.thumbnail(max_size)

        buffer = BytesIO()
        img.save(buffer, format='JPEG', quality=quality)
        buffer.seek(0)

        return InMemoryUploadedFile(
            buffer,
            'ImageField',
            image.name.split('.')[0] + ".jpg",
            'image/jpeg',
            sys.getsizeof(buffer),
            None
        )
    except Exception:
        return image
    


class User(AbstractUser):
    ROLE_CHOICES = (
        ('admin', 'Admin'),
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
    profile_picture = CloudinaryField(folder ='riders_profile/', blank=True, null=True)
    rider_image_1 = CloudinaryField(folder ='riders_images1/', blank=True, null=True)
    rider_image_with_vehicle = CloudinaryField(folder ='riders_vehicle_images2/', blank=True, null=True)
    vehicle_number = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    rating = models.FloatField(default=0)
    rating_count = models.IntegerField(default=0) 
    # Status fields
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
 
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

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
        ('paid', 'Paid'),
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

    delivery_code = models.CharField(max_length=6, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_available(self):
        return self.status == 'pending' and self.rider is None

    # ✅ helper method
    def generate_unique_delivery_code(self):
        while True:
            code = f"{random.randint(0, 999999):06d}"
            if not Package.objects.filter(
                delivery_code=code,
                status__in=['pending', 'accepted', 'picked_up']
            ).exists():
                return code

    # ✅ FIXED SAVE METHOD (ONLY FIXED HERE)
    def save(self, *args, **kwargs):
        if not self.package_id:
            self.package_id = f"PKG-{uuid.uuid4().hex[:8].upper()}"

        # 🔥 SAFE DECIMAL HANDLING (NO STRUCTURE CHANGE)
        if self.price is None:
            raise ValueError("Price is required before saving package")

        price = self.price  # Django already gives Decimal

        # commission calculation
        base_fee = Decimal('200')
        percentage = Decimal('0.10')

        self.commission = base_fee + (price * percentage)

        # rider earning calculation
        self.rider_earning = price - self.commission

        # prevent negative earnings
        if self.rider_earning < 0:
            self.rider_earning = Decimal('0')

        # delivery code
        if not self.delivery_code:
            self.delivery_code = self.generate_unique_delivery_code()
        
        if self.is_paid and self.status == "pending":
            self.status = "paid"

        super().save(*args, **kwargs)

    # ✅ FIXED: now properly OUTSIDE save()
    def hide_delivery_code(self, user):
        if user.role != "customer":
            return None
        return self.delivery_code

    # ✅ FIXED: properly OUTSIDE save()
    def get_delivery_code_for_user(self, user):
        if user.role == "customer" and self.customer_id == user.id:
            return self.delivery_code
        return None

    class Meta:
        ordering = ['-created_at']


        
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


class Withdrawal(models.Model):
    STATUS = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("processing", "Processing"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]

    rider = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    bank_account = models.CharField(max_length=50)
    bank_code = models.CharField(max_length=10)

    status = models.CharField(max_length=20, choices=STATUS, default="pending")

    recipient_code = models.CharField(max_length=100, null=True, blank=True)
    reference = models.CharField(max_length=100, null=True, blank=True)

    failure_reason = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
     return f"{self.rider.riderprofile.rider_id} - {self.amount} - {self.status}"


