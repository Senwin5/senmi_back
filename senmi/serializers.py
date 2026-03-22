
from rest_framework import serializers
from .models import Rider

class RiderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rider
        fields = '__all__'