# senmi/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .serializers import RegisterSerializer, RiderProfileSerializer


class RegisterView(APIView):
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response({
                "message": "User created successfully",
                "role": user.role
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=400)


class RiderProfileUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request):
        profile = request.user.riderprofile
        serializer = RiderProfileSerializer(profile, data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Profile updated"})

        return Response(serializer.errors, status=400)