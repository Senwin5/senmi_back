from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
# Custom permission to block pending riders
from rest_framework.permissions import BasePermission
from rest_framework.permissions import IsAuthenticated, BasePermission, IsAdminUser
from rest_framework.decorators import api_view, permission_classes
from django.core.mail import send_mail
from django.conf import settings
from .serializers import RegisterSerializer, RiderProfileSerializer, CustomLoginSerializer
from rest_framework_simplejwt.views import TokenObtainPairView


class CustomLoginView(TokenObtainPairView):
    serializer_class = CustomLoginSerializer


class RegisterView(APIView):
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()

            # ------------------------
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
                fail_silently=True,  # True in dev, False in production
            )
            # ------------------------

            return Response({
                "message": "User created successfully",
                "role": user.role
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    


# senmi/views.py
class RiderProfileUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request):
        if request.user.role != 'rider':
            return Response({"detail": "Only riders can edit profile."}, status=status.HTTP_403_FORBIDDEN)

        profile = request.user.riderprofile
        serializer = RiderProfileSerializer(profile, data=request.data)
        if serializer.is_valid():
            serializer.save(status='pending')  # mark as pending after edit

            # --- Email to rider ---
            send_mail(
                subject="Rider Profile Submitted",
                message="Your rider profile has been submitted successfully and is pending admin review.",
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
                message=f"Rider {request.user.username} has submitted their profile. Please review and approve.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=admins,
                fail_silently=True,
            )

            return Response({"message": "Profile submitted successfully and is pending admin review."}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    


# -------------------------------
# Admin review API
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