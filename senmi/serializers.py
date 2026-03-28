from importlib.resources import Package

from rest_framework import serializers
from .models import User, RiderProfile
from django.contrib.auth.hashers import make_password
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

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


class CustomLoginSerializer(TokenObtainPairSerializer):

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username
        token['role'] = user.role
        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        user = self.user

        # 🔒 BLOCK RIDERS IF NOT READY
        if user.role == 'rider':
            profile = getattr(user, 'riderprofile', None)

            if not profile:
                raise serializers.ValidationError({
                    "detail": "Complete your profile before logging in."
                })

            if profile.status == 'pending':
                raise serializers.ValidationError({
                    "detail": "Your profile is pending admin approval."
                })

            if profile.status == 'rejected':
                raise serializers.ValidationError({
                    "detail": f"Profile rejected: {profile.rejection_reason}"
                })

        # ✅ keep your existing logic
        data['user_id'] = user.user_id
        data['role'] = user.role

        return data
    



class PackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Package
        fields = '__all__'
        read_only_fields = ['status', 'rider', 'commission']