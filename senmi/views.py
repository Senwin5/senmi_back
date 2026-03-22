from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated, IsAdminUser
from rest_framework.decorators import api_view, permission_classes
from django.core.mail import send_mail
from django.conf import settings
import uuid
from senmi.models import User
from .serializers import RegisterSerializer, RiderProfileSerializer, CustomLoginSerializer
from rest_framework_simplejwt.views import TokenObtainPairView


class CustomLoginView(TokenObtainPairView):
    serializer_class = CustomLoginSerializer


class RegisterView(APIView):
    def post(self, request):
        email = request.data.get('email')
        username = request.data.get('username')

        if User.objects.filter(email=email).exists():
            return Response({"error": "Email is already in use."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()

            # Send email based on role
            if user.role == 'rider':
                subject = "Welcome to SenMi!"
                message = (
                    f"Hello {user.username},\n\n"
                    "Your account has been created successfully as a Rider.\n"
                    "Please update your rider profile to start using the app."
                )
            else:  # customer
                subject = "Welcome to SenMi!"
                message = (
                    f"Hello {user.username},\n\n"
                    "Your account has been created successfully."
                )

            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )

            return Response({
                "message": "User created successfully",
                "role": user.role
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class RiderProfileUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request):
        if request.user.role != 'rider':
            return Response({"detail": "Only riders can edit profile."}, status=status.HTTP_403_FORBIDDEN)

        profile = request.user.riderprofile
        serializer = RiderProfileSerializer(profile, data=request.data)

        if serializer.is_valid():
            # Required text fields
            required_fields = ['full_name', 'phone_number', 'vehicle_number', 'address', 'city']
            missing_text_fields = [field for field in required_fields if not request.data.get(field)]

            # Required image fields
            required_images = ['profile_picture', 'rider_image_1', 'rider_image_with_bike']
            missing_images = [field for field in required_images if not request.FILES.get(field) and not getattr(profile, field)]

            if missing_text_fields or missing_images:
                errors = {}
                if missing_text_fields:
                    errors['missing_fields'] = f"Missing required fields: {', '.join(missing_text_fields)}"
                if missing_images:
                    errors['missing_images'] = f"Missing required images: {', '.join(missing_images)}"
                return Response(errors, status=status.HTTP_400_BAD_REQUEST)

            # Save profile as pending
            serializer.save(status='pending')

            # --- Email to rider ---
            send_mail(
                subject="Rider Profile Submitted",
                message=f"Your rider profile (ID: {profile.rider_id}) has been submitted successfully and is pending admin review.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[request.user.email],
                fail_silently=True,
            )

            # --- Email to admins ---
            from django.contrib.auth import get_user_model
            User = get_user_model()
            admins = User.objects.filter(is_superuser=True).values_list('email', flat=True)
            send_mail(
                subject="New Rider Profile Pending Review",
                message=f"Rider {request.user.username} (ID: {profile.rider_id}) has submitted their profile. Please review and approve.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=admins,
                fail_silently=True,
            )

            return Response({
                "message": "Profile submitted successfully and is pending admin review.",
                "rider_id": profile.rider_id
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def review_rider(request, rider_id):
    from .models import RiderProfile

    try:
        profile = RiderProfile.objects.get(id=rider_id)
    except RiderProfile.DoesNotExist:
        return Response({"error": "Rider not found"}, status=404)

    status_value = request.data.get('status')
    reason = request.data.get('rejection_reason', '')

    if status_value not in ['approved', 'rejected']:
        return Response({"error": "Invalid status"}, status=400)

    profile.status = status_value
    profile.rejection_reason = reason
    profile.save()

    # --- Email to rider ---
    message = (
        f"Your rider profile has been approved."
        if status_value == 'approved'
        else f"Your rider profile has been rejected. Reason: {reason}"
    )
    send_mail(
        subject="Rider Profile Review",
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[profile.user.email],
        fail_silently=True,
    )

    return Response({"message": f"Rider profile {status_value} successfully."}, status=200)


class IsApprovedRider(BasePermission):
    def has_permission(self, request, view):
        if request.user.role == 'rider':
            profile = getattr(request.user, 'riderprofile', None)
            return profile is not None and profile.status == 'approved'
        return True  # other roles are allowed
    

from .models import Package
from django.http import JsonResponse

class AvailablePackagesView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def get(self, request):
        rider_profile = getattr(request.user, 'riderprofile', None)
        if not rider_profile:
            return Response({"error": "Rider profile not found"}, status=404)

        rider_city = rider_profile.city.strip().lower()  # normalize for comparison

        # Filter packages: pending, unassigned, pickup address contains rider's city
        packages = Package.objects.filter(
            status='pending',
            rider__isnull=True,
        )

        # Only include packages in rider's city
        packages = [p for p in packages if rider_city in p.pickup_address.lower()]

        data = []
        for p in packages:
            data.append({
                "id": p.id,
                "description": p.description,
                "pickup": p.pickup_address,
                "delivery": p.delivery_address,
                "price": float(p.price),
                "receiver_name": p.receiver_name,
                "receiver_phone": p.receiver_phone,
            })

        return Response(data)





from django.views.decorators.csrf import csrf_exempt
import json


class AcceptPackageView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def post(self, request, package_id):
        try:
            package = Package.objects.get(id=package_id)
        except Package.DoesNotExist:
            return Response({"error": "Package not found"}, status=404)

        # ✅ Only riders allowed
        if request.user.role != 'rider':
            return Response({"error": "Only riders can accept"}, status=403)

        # ✅ Prevent multiple riders
        if package.rider is not None:
            return Response({"error": "Already taken"}, status=400)

        # Assign rider
        package.rider = request.user
        package.status = 'accepted'
        package.save()

        return Response({"message": "Accepted successfully"})