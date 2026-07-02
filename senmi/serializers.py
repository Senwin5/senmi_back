from decimal import Decimal
from venv import logger

from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from django.contrib.auth import authenticate
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.db import IntegrityError

from senmi.utils import send_fcm_notification
from .models import User, RiderProfile, Package, PackageTracking
from .utils import calculate_distance

from rest_framework.exceptions import AuthenticationFailed
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

class RegisterSerializer(serializers.ModelSerializer):
    phone_number = serializers.CharField(required=False)

    class Meta:
        model = User
        fields = ['email', 'username', 'password', 'role', 'phone_number']

    def validate(self, attrs):
        role = attrs.get('role')
        phone = attrs.get('phone_number')
        if role == 'customer' and not phone:
            raise serializers.ValidationError({"phone_number": "Phone number is required for customers."})
        return attrs

    def create(self, validated_data):
        validated_data['password'] = make_password(validated_data['password'])
        user = super().create(validated_data)

        return user
    


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['username', 'email', 'phone_number', 'role']
        


# serializers.py
    
class RiderProfileSerializer(serializers.ModelSerializer):
    email = serializers.CharField(source='user.email', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)

    #profile_picture = serializers.SerializerMethodField()
    profile_picture = serializers.ImageField(required=False)

    class Meta:
        model = RiderProfile
        fields = [
            'rider_id',
            'full_name',
            'phone_number',
            'vehicle_number',
            'address',
            'city',
            'status',
            'email',
            'username',
            'profile_picture',
            'rider_image_1',
            'rider_image_with_vehicle',
            'rating',
            'rating_count',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)

        request = self.context.get("request")

        if instance.profile_picture:
            if request:
                data["profile_picture"] = request.build_absolute_uri(
                    instance.profile_picture.url
                )
            else:
                data["profile_picture"] = instance.profile_picture.url

        return data



class PackageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source='customer.username', read_only=True)
    sender_phone = serializers.CharField(source='customer.phone_number', read_only=True)

    rider_name = serializers.CharField(source='rider.username', read_only=True)
    rider_phone = serializers.CharField(source='rider.phone_number', read_only=True)

    # ✅ already there
    package_id = serializers.CharField(read_only=True)

    # ✅ ADD THIS (only change)
    delivery_code = serializers.SerializerMethodField()

    rider_profile_picture = serializers.SerializerMethodField()
    vehicle_number = serializers.SerializerMethodField()
      # 🔥 ADD THIS
    eta_minutes = serializers.SerializerMethodField()

    class Meta:
        model = Package
        fields = [
            'id',
            'package_id',
            #'description',
            'pickup_address',
            'delivery_address',
            'pickup_lat',
            'pickup_lng',
            'delivery_lat',
            'delivery_lng',
            'price',
            'status',
            'receiver_name',
            'receiver_phone',
            'payment_type',
            'is_paid',
            'commission',
            'rider_earning',
            'delivery_code',   # ADD THIS BACK
            'sender_name',
            'sender_phone',
            'rider_name',
            'rider_phone',
             # extra info
            'rider_profile_picture',
            'vehicle_number',
             #ADD THIS
            'eta_minutes',
        ]

        read_only_fields = [
            'status',
            'commission',
            'rider_earning',
            'package_id',
            'is_paid'
        ]

    # ✅ ADD THIS METHOD (core fix)
    def get_delivery_code(self, obj):
        request = self.context.get('request')

        if request and request.user == obj.customer:
            return obj.delivery_code  # ✅ ONLY customer sees

        return None  # ❌ rider sees null

    def create(self, validated_data):
        price = self.initial_data.get('price')

        if price:
            validated_data['price'] = Decimal(price)

        return super().create(validated_data)
    
    def get_rider_profile_picture(self, obj):
        if obj.rider and hasattr(obj.rider, 'riderprofile'):

            request = self.context.get('request')
            image = obj.rider.riderprofile.profile_picture

            if image and request:
                return request.build_absolute_uri(image.url)

        return None
    
    
    def get_vehicle_number(self, obj):
        if obj.rider and hasattr(obj.rider, 'riderprofile'):
            return obj.rider.riderprofile.vehicle_number

        return None
    
    def get_eta_minutes(self, obj):
       
        tracking = PackageTracking.objects.filter(
            package=obj
        ).order_by('-timestamp').first()

        if tracking:
            remaining_km = calculate_distance(
                tracking.latitude,
                tracking.longitude,
                obj.delivery_lat,
                obj.delivery_lng
            )
        else:
            remaining_km = calculate_distance(
                obj.pickup_lat,
                obj.pickup_lng,
                obj.delivery_lat,
                obj.delivery_lng
            )

        return max(0, round(remaining_km * 4))


        

class CustomLoginSerializer(TokenObtainPairSerializer):

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username
        token['role'] = user.role
        token['is_admin'] = user.is_superuser or user.is_staff
        return token

    def validate(self, attrs):
        # Step 1: Authenticate user
        authenticate_kwargs = {
            self.username_field: attrs[self.username_field],
            'password': attrs['password'],
        }
        user = authenticate(**authenticate_kwargs)

        if user is None:
            raise AuthenticationFailed("Invalid credentials check email and password")

        # Step 2: Block riders if profile incomplete
        if user.role == 'rider':
            profile = getattr(user, 'riderprofile', None)
            if not profile:
                raise AuthenticationFailed("Complete your profile before logging in.")
            if profile.status == 'pending':
                raise AuthenticationFailed("Your profile is pending admin approval.")
            if profile.status == 'rejected':
                raise AuthenticationFailed(f"Profile rejected: {profile.rejection_reason}")

        # Step 3: Generate JWT token
        data = super().validate(attrs)

        try:
            if user.role.lower() == "rider":
                send_fcm_notification(
                    user,
                    "Welcome back Rider 🚴",
                    "You have successfully logged in",
                    {"type": "login"}
                )
            else:
                send_fcm_notification(
                    user,
                    "Welcome back",
                    "You have successfully logged in",
                    {"type": "login"}
                )

        except Exception as e:
            logger.exception(f"Login notification failed: {e}")


        data['user_id'] = user.user_id
        data['role'] = user.role
        data['username'] = user.username

        data['is_admin'] = user.is_superuser or user.is_staff
        return data
    


class AdminAnalyticsSerializer(serializers.Serializer):
    total_deliveries = serializers.IntegerField()
    completed_deliveries = serializers.IntegerField()
    failed_deliveries = serializers.IntegerField()
    total_revenue = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_rider_payout = serializers.DecimalField(max_digits=10, decimal_places=2)
    average_delivery_time = serializers.CharField()