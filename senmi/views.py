from rest_framework import viewsets
from .models import Rider
from .serializers import RiderSerializer

class RiderViewSet(viewsets.ModelViewSet):
    queryset = Rider.objects.all()
    serializer_class = RiderSerializer