from gc import get_stats
import random
import uuid
import hashlib
import hmac
import json
import logging
import requests
from decimal import Decimal, InvalidOperation
import re
from rest_framework.parsers import JSONParser
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.db import IntegrityError, transaction
from django.db.models import Q, Avg, Count, Prefetch
from django.contrib.auth import authenticate
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated, IsAdminUser
from rest_framework.decorators import api_view, permission_classes
from rest_framework.throttling import UserRateThrottle
from django.shortcuts import get_object_or_404
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from channels.layers import get_channel_layer
from rest_framework.pagination import PageNumberPagination
from asgiref.sync import async_to_sync
from .serializers import UserSerializer
from .utils import send_email, calculate_distance, calculate_price
from .models import (
    Package, PackageStatusHistory, PackageTracking,
    RiderRating, RiderWallet, RiderProfile,Withdrawal
)
from .serializers import (
    RegisterSerializer, RiderProfileSerializer, CustomLoginSerializer,
    PackageSerializer
)
from senmi.models import User


# ------------------------------
# Authentication / Login
# ------------------------------
class CustomLoginView(TokenObtainPairView):
    serializer_class = CustomLoginSerializer

class StandardPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100

# ------------------------------
# Logging
# ------------------------------
logger = logging.getLogger(__name__)


# ------------------------------
# Throttling
# ------------------------------
class LoginThrottle(UserRateThrottle):
    rate = '5/min'


class RiderLoginAPIView(APIView):
    throttle_classes = [LoginThrottle]

    def post(self, request):
        email = request.data.get("email")
        password = request.data.get("password")
        user = authenticate(username=email, password=password)

        if not user:
            return Response({"detail": "Invalid credentials"}, status=401)

        if user.role == 'rider':
            profile = getattr(user, 'riderprofile', None)
            if not profile:
                return Response({"detail": "Complete your profile before logging in."}, status=403)
            if profile.status == 'pending':
                return Response({"detail": "Your profile is pending admin approval."}, status=403)
            if profile.status == 'rejected':
                return Response({"detail": f"Profile rejected: {profile.rejection_reason}"}, status=403)

        refresh = RefreshToken.for_user(user)
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "role": user.role,
            "username": user.username,
            "is_admin": user.is_superuser
        })


class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)
# ------------------------------
# Admin Views
# ------------------------------
class AdminRidersListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        riders = RiderProfile.objects.select_related('user').all()
        data = [{
            "id": r.id,
            "username": r.user.username,
            "email": r.user.email,
            "status": r.status,
            "phone": r.phone_number,
            "city": r.city,
            "profile_picture": r.profile_picture.url if r.profile_picture else None,
            "rider_image_1": r.rider_image_1.url if r.rider_image_1 else None,
            "rider_image_with_vehicle": r.rider_image_with_vehicle.url if r.rider_image_with_vehicle else None,
        } for r in riders]

        paginator = StandardPagination()
        result = paginator.paginate_queryset(data, request)
        return paginator.get_paginated_response(result)


class AdminUserSearchView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        query = request.GET.get('q')
        if not query:
            return Response({"error": "Enter search query"}, status=400)

        users = User.objects.filter(
            Q(email__icontains=query) |
            Q(username__icontains=query) |
            Q(user_id__icontains=query)
        )
        return Response([{"user_id": u.user_id, "email": u.email, "role": u.role, "is_active": u.is_active} for u in users])


@api_view(['POST'])
@permission_classes([IsAdminUser])
def review_rider(request, rider_id):
    """Approve or reject a rider profile""" 
    try:
        profile = RiderProfile.objects.get(id=rider_id)
    except RiderProfile.DoesNotExist:
        return Response({"error": "Rider not found"}, status=404)

    data = request.data
    status_value = data.get('status')
    reason = data.get('rejection_reason', '').strip()

    if not status_value:
        return Response({"error": "Status field is required"}, status=400)
    if status_value not in ['approved', 'rejected']:
        return Response({"error": "Invalid status. Must be 'approved' or 'rejected'."}, status=400)
    if status_value == 'rejected' and not reason:
        return Response({"error": "Rejection reason is required when rejecting a profile."}, status=400)

    profile.status = status_value
    profile.rejection_reason = reason if status_value == 'rejected' else ''
    profile.save(update_fields=['status', 'rejection_reason'])

    #message = f"Your rider profile has been {'approved' if status_value == 'approved' else f'rejected: {reason}'}"
    message = (
            f"""
        Hello {profile.user.username},

        """
            + (
                f"""
        Congratulations!

        We are pleased to inform you that your rider profile has been officially approved by the Senmi Verification Team.

        Your application has successfully passed our review process, and your rider account is now fully activated.

        You can now start accepting delivery requests, completing deliveries, and earning through the Senmi platform.

        As an approved rider, please ensure that you:
        • Follow all Senmi Terms and Conditions
        • Maintain professionalism when interacting with customers
        • Handle deliveries with care and responsibility
        • Keep your rider profile information updated

        We are excited to have you as part of the Senmi rider community and look forward to your success on the platform.

        Thank you for choosing Senmi.

        Ride safely and deliver confidently.

        Best regards,
        Senmi Rider Verification Team
        """
                if status_value == "approved"
                else f"""
        We regret to inform you that your rider profile was not approved during our review process.

        Reason for rejection:
        {reason}

        This decision may have resulted from incomplete information, incorrect details, or verification requirements that were not fully met.

        Please review your submitted profile carefully, make the necessary corrections, and resubmit your application for another review.

        We encourage you to try again, and our team will be happy to reassess your updated submission.

        Thank you for your interest in becoming a Senmi rider.

        Best regards,
        Senmi Rider Verification Team
        """
            )
        )

    recipients = [settings.NOTIFY_EMAIL, profile.user.email]

    send_email(subject="Rider Profile Review", message=message, recipients=recipients)

    return Response({"message": f"Rider profile {status_value} successfully."}, status=200)



# ------------------------------
# Registration
# ------------------------------
class RegisterView(APIView):
    throttle_classes = [LoginThrottle]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            try:
                user = serializer.save()
            except IntegrityError as e:
                if 'email' in str(e).lower():
                    return Response(
                        {"error": "User with this email already exists."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                return Response(
                    {"error": "Database error: " + str(e)},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Send email notification
            try:
                #admin_emails = list(User.objects.filter(is_superuser=True).values_list('email', flat=True))
                recipients = [user.email] +  [settings.NOTIFY_EMAIL]
                send_email(
                    subject="Welcome to Senmi!",
                    message=f"Hello {user.username}, Your account has been created successfully as a {user.role.capitalize()}. Kindly complete your profile for approval by the admin",
                    recipients=recipients
                )
            except Exception as e:
                print("Email sending failed:", e)

            # Return JWT
            refresh = RefreshToken.for_user(user)
            return Response({
                "success": True,
                "message": "User created successfully",
                "role": user.role,
                "username": user.username,
                "access": str(refresh.access_token),
                "refresh": str(refresh)
                
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

# ------------------------------
# Rider Profile
# ------------------------------
class RiderProfileUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    # ✅ ADDED (this is the missing part — DO NOT change your logic)
    def get(self, request):
        if request.user.role != 'rider':
            return Response({"error": "Only riders allowed"}, status=403)

        profile = getattr(request.user, 'riderprofile', None)

        # If new rider (no profile yet)
        if not profile:
            return Response({}, status=200)

        serializer = RiderProfileSerializer(profile)
        return Response(serializer.data, status=200)

    # ✅ YOUR ORIGINAL CODE (UNCHANGED)
    def put(self, request):
        if request.user.role != 'rider':
            return Response({"detail": "Only riders can edit profile."}, status=403)

        profile = request.user.riderprofile
        serializer = RiderProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            required_fields = ['full_name', 'phone_number', 'vehicle_number', 'address', 'city']
            missing_text = [f for f in required_fields if not request.data.get(f)]
            
            required_images = ['profile_picture', 'rider_image_1', 'rider_image_with_vehicle']
            missing_images = [f for f in required_images if not request.FILES.get(f) and not getattr(profile, f)]

            if missing_text or missing_images:
                errors = {}
                if missing_text:
                    errors['missing_fields'] = f"Missing required fields: {', '.join(missing_text)}"
                if missing_images:
                    errors['missing_images'] = f"Missing required images: {', '.join(missing_images)}"
                return Response(errors, status=400)

            # Optional: validate phone number
            phone = request.data.get('phone_number')
            if phone and not re.fullmatch(r'^\+?\d{7,15}$', phone):
                return Response({"error": "Invalid phone number"}, status=400)

            serializer.save(status='pending')

            try:
                # Send to rider + your notify email ONLY
                recipients = [request.user.email, settings.NOTIFY_EMAIL]
                recipients = [r for r in recipients if r]

                '''send_email(
                    subject="Rider Profile Submitted",
                    message=f"Hello {request.user.username}, your rider profile (ID: {profile.rider_id}) has been submitted successfully and is pending review.",
                    recipients=recipients
                )'''


                send_email(
                    subject="🚴 Rider Profile Submitted",
                    message=(
                        f"Hello {request.user.username},\n\n"
                        f"Your rider profile (ID: {profile.rider_id}) has been submitted successfully.\n\n"
                        f"Our team will review your application and notify you shortly.\n\n"
                        f"Thank you for joining Senmi."
                    ),
                    recipients=recipients
                )

            except Exception as e:
                logger.exception("Failed to send profile submission emails")

            return Response({"message": "Profile submitted successfully and is pending admin review.", "rider_id": profile.rider_id})

        return Response(serializer.errors, status=400)
    


# ------------------------------
# Rider Permissions
# ------------------------------
class IsApprovedRider(BasePermission):
    def has_permission(self, request, view):
        if request.user.role == 'rider':
            profile = getattr(request.user, 'riderprofile', None)
            return profile is not None and profile.status == 'approved'
        return True
    


# ------------------------------
# Packages
# ------------------------------
class AvailablePackagesView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def get(self, request):
        rider_profile = getattr(request.user, 'riderprofile', None)
        if not rider_profile:
            return Response({"error": "Rider profile not found"}, status=404)

        rider_city = rider_profile.city.strip().lower()

        packages = Package.objects.filter(
            status='paid',          # 🔥 ONLY PAID PACKAGES
            is_paid=True,           # 🔥 DOUBLE SAFETY CHECK
            rider__isnull=True,
            pickup_address__icontains=rider_city,
            pickup_lat__isnull=False
        ).order_by('-created_at')

        data = []
        for p in packages:
            #net_earning = float(p.rider_earning - p.commission)
            net_earning = float(p.rider_earning)

            data.append({
                "package_id": p.package_id,
                "description": p.description,
                "pickup": p.pickup_address,
                "price": float(p.price),
                "receiver_name": p.receiver_name,
                "receiver_phone": p.receiver_phone,
                "commission": float(p.commission),
                "rider_earning": float(p.rider_earning),
                "net_earning": max(net_earning, 0)
            })

        paginator = StandardPagination()
        result = paginator.paginate_queryset(data, request)
        return paginator.get_paginated_response(result)



class AcceptPackageView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def post(self, request, package_id):

        try:
            with transaction.atomic():

                # 🔥 LOCK package to avoid 2 riders accepting same job
                package = Package.objects.select_for_update().get(package_id=package_id)

                # =========================
                # ✅ VALIDATION MUST BE FIRST
                # =========================

                # 🚫 only riders allowed
                if request.user.role != 'rider':
                    return Response({"error": "Only riders can accept"}, status=403)

                # 💰 MUST be paid BEFORE acceptance
                if not package.is_paid:
                    return Response({"error": "This package has not been paid for"}, status=400)

                # 🚫 already taken
                if package.rider is not None:
                    return Response({"error": "Package already taken"}, status=400)
                
                # 🚫 Rider must not have active package
                active_package_exists = Package.objects.filter(
                    rider=request.user,
                    status__in=['accepted', 'picked_up']
                ).exists()

                if active_package_exists:
                    return Response({
                        "error": "You already have an active delivery. Complete it first."
                    }, status=400)

                # =========================
                # ✅ ASSIGN RIDER
                # =========================
                package.rider = request.user
                package.status = 'accepted'
                package.save()

                PackageStatusHistory.objects.create(
                    package=package,
                    status='accepted'
                )

                # =========================
                # 🔔 NOTIFY OTHER RIDERS
                # =========================
                try:
                    channel_layer = get_channel_layer()
                    async_to_sync(channel_layer.group_send)(
                        "riders",
                        {
                            "type": "package_taken",
                            "data": {
                                "package_id": package.id
                            }
                        }
                    )
                except Exception as e:
                    logger.exception(f"WebSocket error: {e}")

                # =========================
                # 📧 EMAIL NOTIFICATION
                # =========================
                recipients = [
                    package.customer.email,
                    #request.user.email,
                    settings.NOTIFY_EMAIL
                ]

                send_email(
                    subject="📦 Package Accepted",
                    message=(
                        f"Hello {package.customer.username},\n\n"
                        f"Your package {package.package_id} has been accepted by a rider.\n\n"
                        f"Rider Name: {request.user.username}\n"
                        f"Rider Phone: {request.user.phone_number}\n\n"
                        f"The rider will proceed to pick up your package shortly.\n\n"
                        f"After picking up the package rider will start delivery.\n\n"
                        f"Thank you for using Senmi."
                    ),
                    recipients=[r for r in recipients if r]
                )

                # =========================
                # 💰 RESPONSE
                # =========================
                #net_earning = float(package.rider_earning - package.commission)
                net_earning = float(package.rider_earning)

                return Response({
                    "message": "Your package has been accepted successfully",
                    "net_earning": net_earning
                }, status=200)

        except Package.DoesNotExist:
            return Response({"error": "Package not found"}, status=404)

        except Exception as e:
            logger.exception(e)
            return Response({"error": "Server error"}, status=500)     



# ------------------------------
# Package Management Views
# ------------------------------
class CreatePackageView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != 'customer':
            return Response({"error": "Only customers can create packages"}, status=403)

        data = request.data.copy()

        # Validate required fields
        required_fields = [
            'description',
            'pickup_address',
            'delivery_address',
            'receiver_name',
            'receiver_phone'
        ]

        missing = [f for f in required_fields if not data.get(f)]
        if missing:
            return Response(
                {"error": f"Missing fields: {', '.join(missing)}"},
                status=400
            )

        # Validate coordinates safely
        try:
            pickup_lat = float(data.get('pickup_lat'))
            pickup_lng = float(data.get('pickup_lng'))
            delivery_lat = float(data.get('delivery_lat'))
            delivery_lng = float(data.get('delivery_lng'))
        except (TypeError, ValueError):
            return Response({"error": "Invalid coordinates"}, status=400)

        # Price calculation
        try:
            distance = calculate_distance(pickup_lat, pickup_lng, delivery_lat, delivery_lng)
            dynamic_price = calculate_price(distance)
            data['price'] = str(Decimal(dynamic_price).quantize(Decimal("0.01")))
        except Exception as e:
            return Response({"error": f"Price calculation failed: {str(e)}"}, status=400)

        # attach coordinates back
        data['pickup_lat'] = pickup_lat
        data['pickup_lng'] = pickup_lng
        data['delivery_lat'] = delivery_lat
        data['delivery_lng'] = delivery_lng

        data['status'] = 'pending'
        data['payment_type'] = 'sender'
        data['is_paid'] = False

        serializer = PackageSerializer(data=data)

        if serializer.is_valid():
            package = serializer.save(customer=request.user)

            # ✅ ADDED EMAIL NOTIFICATION (NO STRUCTURE CHANGED)
            try:
                #admin_emails = list(User.objects.filter(is_superuser=True).values_list('email', flat=True))
                recipients = [request.user.email] + [settings.NOTIFY_EMAIL]

                '''send_email(
                    subject="Package Created Successfully",
                    message=f"Your package {package.package_id} has been created successfully.",
                    recipients=recipients
                )'''

                send_email(
                    subject="📦 Package Created",
                    message=(
                        f"Hello {request.user.username},\n\n"
                        f"Your package {package.package_id} has been created successfully.\n\n"
                        f"Please proceed to payment so a rider can accept your delivery.\n\n"
                        f"Thank you for using Senmi."
                    ),
                    recipients=recipients
                )
            except Exception as e:
                logger.exception(f"Failed to send package creation email: {e}")

            # WebSocket broadcast
            try:
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    "riders",
                    {
                        "type": "new_package",
                        "data": {
                            "id": package.id,
                            "description": package.description,
                            "pickup": package.pickup_address,
                            "delivery": package.delivery_address,
                            "price": float(package.price),
                            "net_earning": float(package.rider_earning),
                        }
                    }
                )
            except Exception as e:
                logger.exception(e)

            return Response({
                "package_id": package.package_id,
                "delivery_code": package.delivery_code,
                "commission": package.commission,
                "rider_earning": package.rider_earning
            }, status=201)

        # 🔥 IMPORTANT: show real error
        logger.error(serializer.errors)
        return Response(serializer.errors, status=400)
    


class UpdateDeliveryStatusView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def post(self, request, package_id):
        try:
            with transaction.atomic():
                package = Package.objects.select_for_update().get(package_id=package_id)

                if package.rider != request.user:
                    return Response({"error": "Not your package"}, status=403)

                #new_status = request.data.get('status')
                new_status = (request.data.get('status') or "").lower().strip()

                # ✅ ADDED CANCEL (NOT CHANGING ANYTHING ELSE)
                if new_status == "cancelled":

                    if package.status != "accepted":
                        return Response({
                            "error": "You can only cancel before pickup"
                        }, status=400)

                    # ✅ SAVE RIDER INFO BEFORE REMOVING
                    rider_user = request.user
                    rider_profile = getattr(rider_user, 'riderprofile', None)
                    rider_id = rider_profile.rider_id if rider_profile else "N/A"

                    # ✅ UPDATE PACKAGE
                    package.status = "paid"
                    package.rider = None
                    package.save()

                    # 🔥 EMAIL NOTIFICATION
                    try:
                        recipients = [
                            package.customer.email,
                            settings.NOTIFY_EMAIL
                        ]

                        send_email(
                            subject="🚫 Delivery Cancelled by Rider",
                            message=(
                                f"Hello {package.customer.username},\n\n"
                                f"Your package {package.package_id} was cancelled by the rider.\n\n"
                                f"Rider Name: {rider_user.username}\n"
                                f"Rider ID: {rider_id}\n\n"
                                f"The package is now available for another rider to accept.\n\n"
                                f"Thank you for using Senmi."
                            ),
                            recipients=[r for r in recipients if r]
                        )

                    except Exception as e:
                        logger.exception("Cancel email failed")

                    # 🔥 BROADCAST (keep yours)
                    try:
                        channel_layer = get_channel_layer()
                        async_to_sync(channel_layer.group_send)(
                            "riders",
                            {
                                "type": "new_package",
                                "data": {
                                    "id": package.id,
                                    "description": package.description,
                                    "pickup": package.pickup_address,
                                    "delivery": package.delivery_address,
                                    "price": float(package.price),
                                    "net_earning": float(package.rider_earning),
                                }
                            }
                        )
                    except Exception as e:
                        logger.exception(e)

                    return Response({
                        "success": True,
                        "message": "Cancelled"
                    })

                valid_flow = {'accepted': 'picked_up', 'picked_up': 'delivered'}

                if package.status not in valid_flow:
                    return Response({"error": "Invalid current status"}, status=400)

                if new_status != valid_flow[package.status]:
                    return Response({"error": "Invalid status transition"}, status=400)

                # Final delivery handling
                if new_status == "delivered":
                    code_input = request.data.get('delivery_code')
                    

                    if package.status == "delivered":
                        return Response({
                            "success": True,
                            "message": "Package already delivered"
                        }, status=200)

                    # ✅ validate code only if not delivered
                    if not code_input or package.delivery_code != code_input:
                        return Response({
                            "success": False,
                            "error": "Invalid or missing delivery code"
                        }, status=400)

                    wallet, _ = RiderWallet.objects.select_for_update().get_or_create(rider=request.user)

                    # Always subtract commission from rider earnings
                    #net_earning = package.rider_earning - package.commission
                    net_earning = package.rider_earning
                    if net_earning < 0:
                        return Response({"error": "Earnings cannot be negative"}, status=400)

                    #wallet.deposit(net_earning)
                    #wallet.save()
                    wallet.balance += net_earning
                    wallet.total_earned += net_earning
                    wallet.save(update_fields=['balance', 'total_earned'])


                    # Mark collected if payment type is receiver
                    if package.payment_type == "receiver" and not package.is_collected:
                        package.is_collected = True
                        package.save(update_fields=['is_collected'])

                    # ✅ ADDED: expire code immediately after successful use
                    package.delivery_code = None
                    package.save(update_fields=['delivery_code'])

                package.status = new_status
                package.save()

                # ✅ KEEP YOUR HISTORY (unchanged)
                PackageStatusHistory.objects.create(package=package, status=new_status)

                # ✅ NEW: BROADCAST STATUS UPDATE (correct position)
                try:
                    channel_layer = get_channel_layer()
                    async_to_sync(channel_layer.group_send)(
                        f"tracking_{package.package_id}",
                        {
                            "type": "send_location",
                            "status": new_status
                        }
                    )
                except Exception as e:
                    logger.exception(f"WebSocket broadcast failed (status update): {e}")

                # Send email after transaction
                recipients = [package.customer.email, package.rider.email] + [settings.NOTIFY_EMAIL]
                recipients = [r for r in recipients if r]

                try:
                    '''send_email(
                        subject=f"Package {package.package_id} Status Update",
                        message=f"Package {package.package_id} is now {new_status}.",
                        recipients=recipients
                    )'''

                    # Choose message based on status (NO LOGIC CHANGE)
                    if new_status == "picked_up":
                        message = (
                            f"Hello {package.customer.username},\n\n"
                            f"Your package {package.package_id} has been picked up.\n\n"
                            f"Rider: {request.user.username}\n\n"
                            f"Your delivery is now in progress.\n\n"
                            f"Thank you for using Senmi."
                        )

                    elif new_status == "delivered":
                        message = (
                            f"Hello {package.customer.username},\n\n"
                            f"Your package {package.package_id} has been successfully delivered.\n\n"
                            f"We hope you had a great experience.\n\n"
                            f"Thank you for using Senmi."
                        )

                    else:
                        # fallback (keeps your original behavior)
                        message = f"Package {package.package_id} is now {new_status}."

                    # Send email (unchanged behavior)
                    send_email(
                        subject=f"📦 Package Update - {package.package_id}",
                        message=message,
                        recipients=recipients
                    )

                except Exception as e:
                    logger.exception(f"Failed to send status update email for package {package.package_id}: {e}")

                return Response({"success": True,"message": f"Package marked as {new_status}"})

        except Package.DoesNotExist:
            return Response({"error": "Package not found"}, status=404)
        except Exception as e:
            logger.exception(f"Error updating package status {package_id}: {e}")
            return Response({"error": "Failed to update package status"}, status=500)
        
        

class RiderActivePackagesView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def get(self, request):
        packages = Package.objects.filter(
            rider=request.user
        ).order_by('-created_at')

        data = {
            "accepted": [],
            "in_transit": [],
            "delivered": []
        }

        for p in packages:
            status = (p.status or "").strip().lower()

            item = {
                "id": p.id,
                "package_id": p.package_id,
                "status": status,
                "pickup": p.pickup_address,
                "delivery": p.delivery_address,
                #"net_earning": float(p.rider_earning - p.commission),
                "net_earning": float(p.rider_earning),
            }

            if status == "accepted":
                data["accepted"].append(item)

            elif status in ["picked_up", "in_transit"]:
                data["in_transit"].append(item)

            elif status == "delivered":
                data["delivered"].append(item)

        return Response(data)
      

    
class RiderEarningsView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def get(self, request):
        wallet = RiderWallet.objects.get(rider=request.user)

        deliveries = Package.objects.filter(
            rider=request.user,
            status='delivered'
        )

        return Response({
            "total_earnings": float(wallet.total_earned),
            "total_deliveries": deliveries.count()
        })


# ------------------------------
# Receiver Payment Views
# ------------------------------
class InitializeReceiverPaymentView(APIView):
    throttle_classes = [LoginThrottle]
    permission_classes = [IsAuthenticated]

    def post(self, request, package_id):
        try:
            # ✅ LOCK to prevent race condition
            with transaction.atomic():
                package = Package.objects.select_for_update().get(package_id=package_id)
        except Package.DoesNotExist:
            return Response({"error": "Package not found"}, status=404)

        # 🔥 detect payer (UNCHANGED)
        payer = request.data.get("payer")

        # =========================
        # BOTH CAN PAY (FIXED)
        # =========================
        if payer in ["sender", "receiver"]:
            email = request.user.email
        else:
            return Response({"error": "Invalid payment attempt"}, status=400)

        # 🔥 already paid
        if package.is_paid:
            #return Response({"message": "Package already paid"}, status=200)
            return Response({"already_paid": True,"message": "Package already paid"}, status=200)

        url = "https://api.paystack.co/transaction/initialize"
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }

        # ✅ SAFE PRICE
        try:
            amount = int(Decimal(str(package.price)) * 100)
        except Exception:
            logger.exception(f"Invalid price for package {package_id}")
            return Response({"error": "Invalid package price"}, status=400)

        # =========================
        # 🔥 FIXED: ALWAYS UNIQUE REFERENCE
        # =========================
        reference = f"PKG-{package.package_id}-{uuid.uuid4().hex[:12]}-{uuid.uuid4().hex[:4]}"

        data = {
            "email": email,
            "amount": amount,
            "reference": reference,
            "callback_url": settings.PAYMENT_CALLBACK_URL
        }

        try:
            res = requests.post(url, json=data, headers=headers, timeout=10)

            # ✅ HANDLE HTTP ERRORS
            if res.status_code != 200:
                logger.error(f"Paystack HTTP Error: {res.status_code} - {res.text}")
                return Response({
                    "error": "Payment gateway error",
                    "body": res.text
                }, status=500)

            # ✅ SAFE JSON PARSE
            try:
                res_data = res.json()
            except Exception:
                logger.error(f"Invalid JSON from Paystack: {res.text}")
                return Response({"error": "Invalid response from payment gateway"}, status=500)

        except requests.exceptions.RequestException:
            logger.exception("Paystack request failed")
            return Response({"error": "Payment request failed"}, status=500)

        # =========================
        # SUCCESS
        # =========================
        if res_data.get("status"):

            # 🔥 FIXED: always overwrite old reference safely
            package.payment_reference = res_data["data"]["reference"]
            package.save(update_fields=['payment_reference'])

            # 🔥 EMAIL (UNCHANGED)
           

            return Response({
                "payment_url": res_data["data"]["authorization_url"],
                "qr_code": f"https://api.qrserver.com/v1/create-qr-code/?data={res_data['data']['authorization_url']}&size=200x200"
            })

        # ❌ FAILURE
        logger.warning(f"Payment initialization failed for package {package_id}: {res_data}")
        return Response({"error": "Payment initialization failed"}, status=400)
    
    
# Paystack Webhook
# ------------------------------
@method_decorator(csrf_exempt, name='dispatch')
class PaystackWebhookView(APIView):
    @method_decorator(csrf_exempt)
    def post(self, request):
        secret = settings.PAYSTACK_SECRET_KEY
        signature = request.headers.get('x-paystack-signature')

        # =========================
        # FIX 1: safer signature check (correct Paystack standard)
        # =========================
        expected_hash = hmac.new(
            secret.encode('utf-8'),
            request.body,
            hashlib.sha512
        ).hexdigest()

        if not signature or not hmac.compare_digest(signature, expected_hash):
            logger.warning("Paystack webhook signature mismatch")
            return Response(status=400)

        try:
            # =========================
            # FIX 2: safe JSON decode
            # =========================
            payload = json.loads(request.body.decode('utf-8'))
        except json.JSONDecodeError:
            logger.error("Invalid JSON received in Paystack webhook")
            return Response(status=400)

        event = payload.get("event")
        data = payload.get("data", {})
        reference = data.get("reference")

        if event != 'charge.success' or not reference:
            logger.info(f"Ignored Paystack webhook event: {event}")
            return Response(status=200)

        try:
            with transaction.atomic():
                package = Package.objects.select_for_update().get(payment_reference=reference)

                if package.is_paid:
                    logger.info(f"Package {package.id} already marked as paid. Ignoring webhook.")
                    return Response(status=200)

                package.is_paid = True
                package.status = "paid" 
                package.save(update_fields=['is_paid','status'])
                logger.info(f"Package {package.id} marked as paid via webhook.")

                recipients = [
                    package.customer.email,
                    package.rider.email if package.rider else None
                ] + [settings.NOTIFY_EMAIL]

                recipients = [r for r in recipients if r]

                send_email(
                    subject="Payment Successful",
                    message=(
                        f"Hello {package.customer.username},\n\n"
                        f"Your payment for package {package.package_id} was successful.\n\n"
                        f"📦 Delivery Code: {package.delivery_code}\n\n"
                        f"⚠️ Please share this code ONLY with the rider upon delivery.\n\n"
                        f"Your package is now available for riders to accept.\n\n"
                        f"Thank you for using Senmi."
                    ),
                    recipients=recipients
                )

        except Package.DoesNotExist:
            logger.warning(f"No package found with payment reference {reference}")
            return Response(status=200)

        except Exception as e:
            logger.exception(f"Error processing Paystack webhook for reference {reference}")
            return Response(status=500)

        return Response(status=200)
    

# ------------------------------
# Package Tracking Views
# ------------------------------
class UpdateLocationView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def post(self, request, package_id):
        try:
            lat = float(request.data.get('lat'))
            lng = float(request.data.get('lng'))
        except (TypeError, ValueError):
            return Response({"error": "Invalid coordinates"}, status=400)

        try:
            #package = Package.objects.get(id=package_id, rider=request.user)
            package = Package.objects.get(package_id=package_id, rider=request.user)
        except Package.DoesNotExist:
            return Response({"error": "Not your package"}, status=403)

        PackageTracking.objects.create(package=package, rider=request.user, latitude=lat, longitude=lng)

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"tracking_{package.package_id}",  # ✅ FIXED
            {
                "type": "send_location",
                "lat": lat,
                "lng": lng,
                "status": package.status,  # ✅ also add this
            }
        )
        return Response({"message": "Location updated"})


class TrackPackageView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, package_id):
        try:
            package = Package.objects.get(package_id=package_id)
        except Package.DoesNotExist:
            return Response({"error": "Package not found"}, status=404)

        if request.user not in [package.customer, package.rider]:
            return Response({"error": "Unauthorized"}, status=403)

        tracking = PackageTracking.objects.filter(package=package).order_by('-timestamp').first()

        # =========================
        # NO TRACKING YET
        # =========================
        if not tracking:
            return Response({
                "package_id": package.package_id,
                "status": package.status,
                "lat": None,
                "lng": None,
                "delivery_lat": package.delivery_lat,
                "delivery_lng": package.delivery_lng,

                "price": package.price,
                "description": package.description,

                "sender_name": package.customer.username,
                "sender_phone": package.customer.phone_number,

                "receiver_name": package.receiver_name,
                "receiver_phone": package.receiver_phone,

                "pickup_address": package.pickup_address,
                "delivery_address": package.delivery_address,

                # ✅ delivery code included
                #"delivery_code": package.delivery_code,
                "delivery_code": package.delivery_code if request.user == package.customer else None,
                
            })

        # =========================
        # TRACKING EXISTS
        # =========================
        return Response({
            "package_id": package.package_id,
            "description": package.description,
            "price": package.price,

            "sender_name": package.customer.username,
            "sender_phone": package.customer.phone_number,

            "receiver_name": package.receiver_name,
            "receiver_phone": package.receiver_phone,

            "pickup_address": package.pickup_address,
            "delivery_address": package.delivery_address,

            "status": package.status,

            "lat": tracking.latitude if tracking else None,
            "lng": tracking.longitude if tracking else None,

            "delivery_lat": package.delivery_lat,
            "delivery_lng": package.delivery_lng,

            # ✅ delivery code included
            #"delivery_code": package.delivery_code,
        })
    


class CustomerPackagesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        latest_tracking = PackageTracking.objects.order_by('-timestamp')
        packages = Package.objects.filter(customer=request.user).select_related('rider').prefetch_related(
            Prefetch('rider__riderprofile'),
            Prefetch('tracking_entries', queryset=latest_tracking, to_attr='latest_tracking')
        )

        data = []
        for p in packages:
            rider_profile = getattr(p.rider, 'riderprofile', None) if p.rider else None
            tracking = p.latest_tracking[0] if getattr(p, 'latest_tracking', []) else None

            # ✅ FIX: proper delivery_code logic (moved OUT of dict)
            delivery_code = None
            if request.user.role == "customer" and request.user == p.customer:
                delivery_code = p.delivery_code

            data.append({
                "id": p.id,
                "description": p.description,
                "price": float(p.price),
                "is_paid": p.is_paid,
                "status": p.status,

                # ✅ SAFE + CLEAN
                "delivery_code": delivery_code,

                "rider": {
                    "username": p.rider.username if p.rider else None,
                    "phone": rider_profile.phone_number if rider_profile else None,
                    "rating": float(rider_profile.rating) if rider_profile else None,
                    "rating_count": rider_profile.rating_count if rider_profile else 0,
                    "net_earning": float(p.rider_earning) if p.rider else 0
                },

                "tracking": {
                    "lat": tracking.latitude if tracking else None,
                    "lng": tracking.longitude if tracking else None
                },

                "created_at": p.created_at,
            })
    
        paginator = StandardPagination()
        result = paginator.paginate_queryset(data, request)
        return paginator.get_paginated_response(result)


    
class PackageDetailView(APIView):
    def get(self, request, package_id):
        try:
            package = Package.objects.get(package_id=package_id)
        except Package.DoesNotExist:
            return Response({"error": "Package not found"}, status=404)

        #serializer = PackageSerializer(package)
        serializer = PackageSerializer(package, context={'request': request})
        return Response(serializer.data)
    
# ------------------------------
# Rider Wallet & Withdrawal
# ------------------------------
class RiderWalletView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def get(self, request):
        wallet, _ = RiderWallet.objects.get_or_create(rider=request.user)

        return Response({
            "balance": float(wallet.balance or 0),
            "total_earned": float(wallet.total_earned or 0),
        })


# ------------------------------
# Rider RidermWithdraw
# ------------------------------
class RiderWithdrawView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):

        try:
            amount = Decimal(request.data.get('amount'))
            if amount <= 0:
                raise InvalidOperation()
        except:
            return Response({"error": "Invalid amount"}, status=400)

        wallet, _ = RiderWallet.objects.get_or_create(rider=request.user)

        # ✅ FIX: NOW amount exists before using it
        if amount > wallet.balance:
            return Response(
                {"error": "Insufficient balance"},
                status=400
            )
        bank_account = request.data.get('bank_account')
        bank_code = request.data.get('bank_code')
        withdrawal = Withdrawal.objects.create(
            rider=request.user,
            amount=amount,
            bank_account=bank_account,
            bank_code=bank_code,
            status="processing"
        )

        if not bank_account or not bank_code:
            return Response({"error": "Bank details required"}, status=400)

        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }

        # ✅ STEP 1: VERIFY ACCOUNT FIRST
        verify_url = f"https://api.paystack.co/bank/resolve?account_number={bank_account}&bank_code={bank_code}"

        try:
            verify_res = requests.get(verify_url, headers=headers)
            verify_json = verify_res.json()
            print("VERIFY RESPONSE:", verify_json)
        except Exception as e:
            return Response({
                "error": "Verification request failed",
                "details": str(e)
            }, status=500)

        if not verify_json.get("status"):
            return Response({
                "error": "Invalid bank details",
                "paystack_message": verify_json.get("message"),
                "full_response": verify_json
            }, status=400)

        account_name = verify_json["data"]["account_name"]

        # ✅ STEP 2: CREATE RECIPIENT
        recipient_data = {
            "type": "nuban",
            "name": account_name,
            "account_number": bank_account,
            "bank_code": bank_code,
            "currency": "NGN"
        }

        recipient_res = requests.post(
            "https://api.paystack.co/transferrecipient",
            json=recipient_data,
            headers=headers
        ).json()

        print("RECIPIENT RESPONSE:", recipient_res)

        if not recipient_res.get("status"):
            if "recipient_code" in str(recipient_res):
                recipient_code = recipient_res["data"].get("recipient_code")
            else:
                return Response({
                    "error": "Recipient creation failed",
                    "details": recipient_res
                }, status=400)
        else:
            recipient_code = recipient_res["data"]["recipient_code"]

        # ✅ STEP 3: TRANSFER
        transfer_data = {
            "source": "balance",
            "amount": int(amount * 100),
            "recipient": recipient_code,
            "reason": "Rider payout"
        }

        transfer_res = requests.post(
            "https://api.paystack.co/transfer",
            json=transfer_data,
            headers=headers
        ).json()

        print("TRANSFER RESPONSE:", transfer_res)

        if not transfer_res.get("status"):
            withdrawal.status = "failed"
            withdrawal.failure_reason = transfer_res.get("message")
            withdrawal.save()

            return Response({
                "error": "Transfer failed",
                "paystack_message": transfer_res.get("message"),
                "details": transfer_res
            }, status=400)

        withdrawal.status = "success"
        withdrawal.save()

        return Response({
            "message": "Withdrawal successful"
        })
    

class AdminWithdrawalsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        withdrawals = Withdrawal.objects.all().order_by("-created_at")

        data = [
            {
                "rider_id": w.rider.riderprofile.rider_id,
                "rider": w.rider.email,
                "amount": float(w.amount),
                "status": w.status,
                "reason": w.failure_reason,
                "created_at": w.created_at
            }
            for w in withdrawals
        ]

        return Response(data)
    

class ApproveWithdrawalView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, withdrawal_id):
        withdrawal = get_object_or_404(Withdrawal, id=withdrawal_id)

        if withdrawal.status not in ["pending", "processing"]:
            return Response(
                {"error": "Cannot approve this withdrawal"},
                status=400
            )

        withdrawal.status = "approved"
        withdrawal.save()

        return Response({
            "message": "Withdrawal approved"
        })
        

class RejectWithdrawalView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, withdrawal_id):
        withdrawal = get_object_or_404(Withdrawal, id=withdrawal_id)

        if withdrawal.status in ["success", "rejected"]:
            return Response(
                {"error": "Cannot reject this withdrawal"},
                status=400
            )

        withdrawal.status = "rejected"
        withdrawal.failure_reason = request.data.get(
            "reason",
            "Rejected by admin"
        )
        withdrawal.save()

        return Response({
            "message": "Withdrawal rejected"
        })

class BankListView(APIView):
    def get(self, request):
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"
        }

        res = requests.get("https://api.paystack.co/bank", headers=headers)

        return Response(res.json())
    


class RetryWithdrawalView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, withdrawal_id):
        withdrawal = get_object_or_404(Withdrawal, id=withdrawal_id)

        if withdrawal.status != "failed":
            return Response(
                {"error": "Only failed withdrawals can be retried"},
                status=400
            )

        withdrawal.status = "processing"
        withdrawal.failure_reason = None
        withdrawal.save()

        process_withdrawal(withdrawal)

        return Response({
            "message": "Withdrawal retry started"
        })
    


def process_withdrawal(withdrawal):
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }

    try:
        transfer_res = requests.post(
            "https://api.paystack.co/transfer",
            json={
                "source": "balance",
                "amount": int(withdrawal.amount * 100),
                "recipient": withdrawal.recipient_code,
                "reason": "Rider payout retry"
            },
            headers=headers
        ).json()

        if transfer_res.get("status"):
            withdrawal.status = "success"
            withdrawal.reference = transfer_res["data"]["reference"]
        else:
            withdrawal.status = "failed"
            withdrawal.failure_reason = transfer_res.get("message")

    except Exception as e:
        withdrawal.status = "failed"
        withdrawal.failure_reason = str(e)

    withdrawal.save()
    

class ResolveAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        account_number = request.data.get("account_number")
        bank_code = request.data.get("bank_code")

        if not account_number or not bank_code:
            return Response({"error": "Missing details"}, status=400)

        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"
        }

        url = f"https://api.paystack.co/bank/resolve?account_number={account_number}&bank_code={bank_code}"

        try:
            res = requests.get(url, headers=headers).json()
        except Exception:
            return Response({"error": "Verification failed"}, status=500)

        if res.get("status"):
            return Response({
                "account_name": res["data"]["account_name"]
            })

        return Response({"error": res.get("message")}, status=400)


# ------------------------------
# Rating & Reviews
# ------------------------------
class RateRiderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, package_id):
        try:
            #package = Package.objects.get(id=package_id, customer=request.user, status='delivered')
            package = Package.objects.get(package_id=package_id,customer=request.user,status='delivered')
        except Package.DoesNotExist:
            return Response({"error": "Invalid package"}, status=404)

        if hasattr(package, 'riderrating'):
            return Response({"error": "Already rated"}, status=400)

        try:
            rating = int(request.data.get('rating'))
        except (TypeError, ValueError):
            return Response({"error": "Rating must be a number"}, status=400)

        if rating < 1 or rating > 5:
            return Response({"error": "Rating must be 1–5"}, status=400)

        comment = request.data.get('comment', '')

        if not package.rider:
            return Response({"error": "No rider assigned"}, status=400)

        RiderRating.objects.create(
            rider=package.rider,
            customer=request.user,
            package=package,
            rating=rating,
            comment=comment
        )

        # Update rider profile stats
        rider_profile = getattr(package.rider, 'riderprofile', None)
        if rider_profile:
            stats = package.rider.ratings.aggregate(avg=Avg('rating'), count=Count('id'))
            rider_profile.rating = round(stats['avg'] or 0, 1)
            rider_profile.rating_count = stats['count'] or 0
            rider_profile.save(update_fields=['rating', 'rating_count'])

        return Response({"message": "Rating submitted"})


# ------------------------------
# Package Timeline & Admin Search
# ------------------------------
class PackageTimelineView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, package_id):
        history = PackageStatusHistory.objects.filter(package_id=package_id).order_by('timestamp')
        return Response([{"status": h.status, "time": h.timestamp} for h in history])


# ------------------------------
# Rider Status
# ------------------------------
class RiderStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'rider':
            return Response({"role": request.user.role})

        profile = getattr(request.user, 'riderprofile', None)
        if not profile:
            return Response({"status": "no_profile"})

        return Response({"status": profile.status, "rejection_reason": profile.rejection_reason})
    
    

class HardDeleteUserView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        print("🔥 HARD DELETE HIT")

        user = request.user

        try:
            with transaction.atomic():

                if user.role == "rider":
                    Package.objects.filter(rider=user).update(rider=None)
                    PackageTracking.objects.filter(rider=user).delete()
                    RiderRating.objects.filter(rider=user).delete()
                    RiderWallet.objects.filter(rider=user).delete()
                    RiderProfile.objects.filter(user=user).delete()

                elif user.role == "customer":
                    RiderRating.objects.filter(customer=user).delete()
                    Package.objects.filter(customer=user).delete()

                email = user.email

                user.delete()

            print("✅ USER DELETED:", email)

            return Response({
                "success": True,
                "message": "Account deleted"
            }, status=200)

        except Exception as e:
            logger.exception("Hard delete failed")
            return Response({"error": str(e)}, status=500)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            token = RefreshToken(refresh_token)
            token.blacklist()  # Requires SimpleJWT with blacklist enabled
            return Response({"detail": "Logged out successfully."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def calculate_price_view(request):
    try:
        pickup_lat = float(request.data.get('pickup_lat'))
        pickup_lng = float(request.data.get('pickup_lng'))
        delivery_lat = float(request.data.get('delivery_lat'))
        delivery_lng = float(request.data.get('delivery_lng'))

        distance = calculate_distance(pickup_lat, pickup_lng, delivery_lat, delivery_lng)
        price = calculate_price(distance)

        return Response({
            "distance_km": round(distance, 2),
            "price": float(price)
        })

    except Exception as e:
        return Response({"error": str(e)}, status=400)
    


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_orders(request):
    packages = Package.objects.filter(
        customer=request.user,
       # status__in=["pending", "paid", "delivered"]
        status__in=["pending", "paid", "accepted", "picked_up", "delivered"]
    ).order_by('-created_at')

    serializer = PackageSerializer(packages, many=True)
    return Response(serializer.data)


class PaymentCallbackView(APIView):
    def get(self, request):
        reference = request.GET.get("reference")

        return Response({
            "message": "Payment completed",
            "reference": reference
        })
    

def search_package(request):
    query = request.GET.get("q", "").strip()

    if not query:
        return JsonResponse({"error": "No search query provided"}, status=400)

    package = Package.objects.filter(
        Q(package_id__icontains=query) |
        Q(payment_reference__icontains=query)
    ).first()

    if not package:
        return JsonResponse({
            "error": "Package not found",
            "debug_query": query
        }, status=404)

    return JsonResponse({
        "success": True,
        "id": package.id,
        "package_id": package.package_id,
        "status": package.status,
        "delivery_code": package.delivery_code,
        "is_paid": package.is_paid,
        "price": str(package.price),
    })



@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_package(request, package_id):
    try:
        package = Package.objects.get(package_id=package_id)

        # 🔒 Only owner can delete
        if package.customer != request.user:
            return Response({"error": "Not allowed"}, status=403)

        # ❌ optional safety: block deletion if already delivered
        if package.status == "delivered":
            return Response({"error": "Cannot delete delivered package"}, status=400)

        package.delete()

        return Response({
            "success": True,
            "message": "Package deleted successfully"
        }, status=200)

    except Package.DoesNotExist:
        return Response({"error": "Package not found"}, status=404)