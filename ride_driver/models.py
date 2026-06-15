from django.db import models
from django.conf import settings
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
    

class SenmiRideDriverProfile(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    driver_id = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        editable=False
    )

    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)

    # Driver Images
    profile_photo = CloudinaryField(
        folder='ride_driver_profile/',
        blank=True,
        null=True
    )

    driver_license_photo = CloudinaryField(
        folder='driver_license/',
        blank=True,
        null=True
    )

    vehicle_photo = CloudinaryField(
        folder='vehicle_photo/',
        blank=True,
        null=True
    )

    # Vehicle Details
    vehicle_brand = models.CharField(max_length=100)
    vehicle_model = models.CharField(max_length=100)
    vehicle_color = models.CharField(max_length=50, blank=True)
    vehicle_year = models.CharField(max_length=10, blank=True)

    plate_number = models.CharField(
        max_length=50,
        unique=True
    )

    # Driver Status
    is_online = models.BooleanField(default=False)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )

    rejection_reason = models.TextField(
        blank=True,
        null=True
    )

    # Ratings
    rating = models.FloatField(default=0)
    rating_count = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.driver_id:
            self.driver_id = f"DRIVER-{uuid.uuid4().hex[:8].upper()}"

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.driver_id} - {self.full_name}"




#Notice this wallet is for commissions.
class SenmiRideDriverWallet(models.Model):
    driver = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    total_commission_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    def __str__(self):
        return f"{self.driver.username} - ₦{self.balance}"


#Driver order
class SenmiRideDriverRequest(models.Model):

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('arrived', 'Arrived'),
        ('started', 'Started'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    passenger = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ride_requests'
    )

    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ride_jobs'
    )

    ride_id = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        editable=False
    )

    pickup_address = models.TextField()
    destination_address = models.TextField()

    pickup_lat = models.FloatField()
    pickup_lng = models.FloatField()

    destination_lat = models.FloatField()
    destination_lng = models.FloatField()

    estimated_distance_km = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    estimated_duration_minutes = models.IntegerField()

    fare = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    commission = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    driver_earning = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):

        if not self.ride_id:
            self.ride_id = f"RIDE-{uuid.uuid4().hex[:8].upper()}"

        super().save(*args, **kwargs)

    def __str__(self):
        return self.ride_id



class SenmiRideDriverTracking(models.Model):
    ride = models.ForeignKey(SenmiRideDriverRequest,on_delete=models.CASCADE,related_name='tracking')
    driver = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    latitude = models.FloatField()
    longitude = models.FloatField()
    timestamp = models.DateTimeField(auto_now_add=True)



class SenmiRideDriverRating(models.Model):
    ride = models.OneToOneField(SenmiRideDriverRequest,on_delete=models.CASCADE)
    passenger = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    driver = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='ride_ratings')
    rating = models.IntegerField()
    comment = models.TextField(blank=True)



class SenmiRideDriverWithdrawal(models.Model):

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]

    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.driver.username} - ₦{self.amount}"
    

class SenmiRideDriverBank(models.Model):
    driver = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    account_name = models.CharField(max_length=255)

    account_number = models.CharField(
        max_length=20
    )

    bank_name = models.CharField(
        max_length=100
    )

    bank_code = models.CharField(
        max_length=20
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.account_name