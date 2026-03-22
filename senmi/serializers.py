# senmi/serializers.py

from rest_framework import serializers
from .models import User, RiderProfile
from django.contrib.auth.hashers import make_password


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