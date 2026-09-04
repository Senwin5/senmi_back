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
        img.save(buffer, format="JPEG", quality=quality)
        buffer.seek(0)

        return InMemoryUploadedFile(
            buffer,
            "ImageField",
            image.name.split(".")[0] + ".jpg",
            "image/jpeg",
            sys.getsizeof(buffer),
            None,
        )

    except Exception:
        return image


# ============================================================
# RIDE DRIVER PROFILE
# ============================================================

class RideDriverProfile(models.Model):

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )

    driver_id = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        editable=False,
    )

    full_name = models.CharField(max_length=255)

    phone_number = models.CharField(max_length=20)

    # Driver Images

    profile_photo = CloudinaryField(
        folder="ride_driver_profile/",
        blank=True,
        null=True,
    )

    driver_license_photo = CloudinaryField(
        folder="driver_license/",
        blank=True,
        null=True,
    )

    vehicle_photo = CloudinaryField(
        folder="vehicle_photo/",
        blank=True,
        null=True,
    )

    # Vehicle Details

    vehicle_brand = models.CharField(max_length=100)

    vehicle_model = models.CharField(max_length=100)

    vehicle_color = models.CharField(
        max_length=50,
        blank=True,
    )

    vehicle_year = models.CharField(
        max_length=10,
        blank=True,
    )

    plate_number = models.CharField(
        max_length=50,
        unique=True,
    )

    # Driver Status

    is_online = models.BooleanField(default=False)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
    )

    rejection_reason = models.TextField(
        blank=True,
        null=True,
    )

    # Ratings

    rating = models.FloatField(default=0)

    rating_count = models.IntegerField(default=0)

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def save(self, *args, **kwargs):

        if not self.driver_id:
            self.driver_id = (
                f"DRIVER-{uuid.uuid4().hex[:8].upper()}"
            )

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.driver_id} - {self.full_name}"


# ============================================================
# RIDE DRIVER WALLET
# ============================================================

class RideDriverWallet(models.Model):

    driver = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ride_wallet",
    )

    # Money available to the driver

    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    # Total commission paid to Senmi

    total_commission_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    def __str__(self):
        return f"{self.driver.username} - ₦{self.balance}"


# ============================================================
# RIDE REQUEST
# ============================================================

class RideRequest(models.Model):

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("arrived", "Arrived"),
        ("started", "Started"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    passenger = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ride_requests",
    )

    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ride_jobs",
    )

    ride_id = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        editable=False,
    )

    pickup_address = models.TextField()

    destination_address = models.TextField()

    pickup_lat = models.FloatField()

    pickup_lng = models.FloatField()

    destination_lat = models.FloatField()

    destination_lng = models.FloatField()

    estimated_distance_km = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    estimated_duration_minutes = models.IntegerField()

    # Total amount passenger pays

    fare = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    # Amount driver owes Senmi

    service_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    # Amount driver keeps

    driver_earning = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    # Cash ride

    payment_method = models.CharField(
        max_length=20,
        choices=[
            ("cash", "Cash"),
        ],
        default="cash",
    )

    # Whether the driver has paid Senmi's commission

    commission_paid = models.BooleanField(
        default=False,
    )

    commission_paid_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    def save(self, *args, **kwargs):

        if not self.ride_id:
            self.ride_id = (
                f"RIDE-{uuid.uuid4().hex[:8].upper()}"
            )

        super().save(*args, **kwargs)

    def __str__(self):
        return self.ride_id


# ============================================================
# RIDE DRIVER TRACKING
# ============================================================

class RideTracking(models.Model):

    ride = models.ForeignKey(
        RideRequest,
        on_delete=models.CASCADE,
        related_name="tracking",
    )

    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )

    latitude = models.FloatField()

    longitude = models.FloatField()

    timestamp = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.ride.ride_id} - {self.timestamp}"


# ============================================================
# RIDE RATING
# ============================================================

class RideRating(models.Model):

    ride = models.OneToOneField(
        RideRequest,
        on_delete=models.CASCADE,
        related_name="rating",
    )

    passenger = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )

    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ride_ratings",
    )

    rating = models.IntegerField()

    comment = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return f"{self.ride.ride_id} - {self.rating}/5"


# ============================================================
# RIDE COMMISSION PAYMENT
# ============================================================

class RideCommissionPayment(models.Model):

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    ]

    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ride_commission_payments",
    )

    ride = models.ForeignKey(
        RideRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commission_payments",
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    # Paystack transaction/reference

    reference = models.CharField(
        max_length=100,
        unique=True,
    )

    payment_url = models.URLField(
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
    )

    paid_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return (
            f"{self.driver.username} - "
            f"₦{self.amount} - "
            f"{self.status}"
        )


# ============================================================
# RIDE COMMISSION TRANSACTION
# ============================================================

class RideCommissionTransaction(models.Model):

    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ride_commission_transactions",
    )

    payment = models.OneToOneField(
        RideCommissionPayment,
        on_delete=models.CASCADE,
        related_name="transaction",
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    reference = models.CharField(
        max_length=100,
        unique=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return (
            f"{self.driver.username} - "
            f"₦{self.amount}"
        )


# ============================================================
# RIDE DRIVER WITHDRAWAL
# ============================================================

class RideWithdrawal(models.Model):

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]

    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ride_withdrawals",
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
    )

    reference = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )

    failure_reason = models.TextField(
        blank=True,
        null=True,
    )

    paid_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return (
            f"{self.driver.username} - "
            f"₦{self.amount} - "
            f"{self.status}"
        )


# ============================================================
# RIDE DRIVER BANK
# ============================================================

class RideBank(models.Model):

    driver = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ride_bank",
    )

    account_name = models.CharField(
        max_length=255,
    )

    account_number = models.CharField(
        max_length=20,
    )

    bank_name = models.CharField(
        max_length=100,
    )

    bank_code = models.CharField(
        max_length=20,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return self.account_name


# ============================================================
# RIDE PRICING CONFIG
# ============================================================

class RidePricingConfig(models.Model):

    name = models.CharField(
        max_length=50,
        default="Default Ride Pricing",
    )

    base_fare = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    per_km_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    per_minute_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    service_fee_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
    )

    is_active = models.BooleanField(
        default=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return self.name