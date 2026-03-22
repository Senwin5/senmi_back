# senmi/serializers.py
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


# senmi/serializers.py
class RiderProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiderProfile
        fields = '__all__'
        read_only_fields = ['status', 'rejection_reason']  # riders cannot set these


class CustomLoginSerializer(TokenObtainPairSerializer):
    # Optional: customize token claims
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username
        token['role'] = user.role
        return token