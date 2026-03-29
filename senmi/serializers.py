from importlib.resources import Package
from rest_framework import serializers
from .models import User, RiderProfile
from django.contrib.auth.hashers import make_password
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth import authenticate

class RegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['email', 'username', 'password', 'role']

    def create(self, validated_data):
        validated_data['password'] = make_password(validated_data['password'])
        return super().create(validated_data)


class RiderProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiderProfile
        fields = '__all__'
        read_only_fields = ['status', 'rejection_reason', 'rider_id']  # riders cannot set these





class PackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Package
        fields = '__all__'
        read_only_fields = ['status', 'rider', 'commission']




class CustomLoginSerializer(TokenObtainPairSerializer):

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username
        token['role'] = user.role
        return token

    def validate(self, attrs):
        # 🔥 STEP 1: authenticate user manually FIRST
        authenticate_kwargs = {
            self.username_field: attrs[self.username_field],
            'password': attrs['password'],
        }

        user = authenticate(**authenticate_kwargs)

        if user is None:
            raise AuthenticationFailed("Invalid credentials")

        # 🔒 STEP 2: BLOCK RIDERS BEFORE TOKEN CREATION
        if user.role == 'rider':
            profile = getattr(user, 'riderprofile', None)

            if not profile:
                raise AuthenticationFailed("Complete your profile before logging in.")

            if profile.status == 'pending':
                raise AuthenticationFailed("Your profile is pending admin approval.")

            if profile.status == 'rejected':
                raise AuthenticationFailed(
                    f"Profile rejected: {profile.rejection_reason}"
                )

        # ✅ STEP 3: NOW generate token safely
        data = super().validate(attrs)

        data['user_id'] = user.user_id
        data['role'] = user.role
        data['username'] = user.username

        return data