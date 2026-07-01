import hashlib
import hmac
import json
import logging
import random
import re
import requests
import uuid
from datetime import timezone
from decimal import Decimal, InvalidOperation
from gc import get_stats
from venv import logger
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, transaction
from django.db.models import (Avg,Count,DurationField,ExpressionWrapper,F,Prefetch,Q,Sum,)
from django.db.models.functions import (ExtractHour,TruncDate,TruncMonth,)
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import JSONParser
from rest_framework.permissions import (AllowAny,BasePermission,IsAuthenticated,)
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from senmi.models import User
from django.contrib.auth.password_validation import validate_password
from math import radians, sin, cos, sqrt, atan2
from senmi.permissions import IsAdminOrSupport
from senmi.utils import (calculate_distance,calculate_price,send_email,)
from .models import (FCMDevice,Package,PackageTracking, PasswordResetOTP,RiderProfile,RiderRating,RiderWallet,Withdrawal,)
from .serializers import (AdminAnalyticsSerializer,CustomLoginSerializer,PackageSerializer,RegisterSerializer,RiderProfileSerializer,UserSerializer,)
from .utils import (notify_admin_dashboard,send_fcm_notification,)



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
                # 🔔 LIVE NOTIFICATIONS (safe block)
                try:
                    send_fcm_notification(
                        user,
                        "Welcome ",
                        "Account created successfully",
                        {"type": "account_created"}
                    )

                    admins = User.objects.filter(is_superuser=True)

                    for admin in admins:
                        send_fcm_notification(
                            admin,
                            "New User 👤",
                            f"New user registered: {user.email}",
                            {"type": "new_user"}
                        )

                except Exception as e:
                    logger.exception(f"Live notification failed: {e}")
                
               
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

            try:
                # User email
                if user.role.lower() == "rider":
                    user_message = (
                        f"Hello {user.username}, "
                        f"Your account has been created successfully as a Rider. "
                        f"Kindly complete your rider profile for approval by the admin."
                    )
                else:
                    user_message = (
                        f"Hello {user.username}, "
                        f"Your account has been created successfully as a "
                        f"{user.role.capitalize()}."
                    )

                send_email(
                    subject="Welcome to Senmi!",
                    message=user_message,
                    recipients=[user.email]
                )

                # Admin email
                if user.role.lower() == "rider":
                    admin_message = (
                        "A new rider has created an account.\n\n"
                        f"Name: {user.username}\n"
                        f"Email: {user.email}\n"
                        "The rider needs approval."
                    )
                    admin_subject = "New Rider Registration"
                elif user.role.lower() == "customer":
                    admin_message = (
                        "A new customer has created an account.\n\n"
                        f"Name: {user.username}\n"
                        f"Email: {user.email}"
                    )
                    admin_subject = "New Customer Registration"
                else:
                    admin_message = (
                        f"A new {user.role} has created an account.\n\n"
                        f"Name: {user.username}\n"
                        f"Email: {user.email}"
                    )
                    admin_subject = f"New {user.role.capitalize()} Registration"

                send_email(
                    subject=admin_subject,
                    message=admin_message,
                    recipients=[settings.NOTIFY_EMAIL]
                )

            except Exception as e:
                logger.exception(
                    f"Registration email failed for {user.email}: {str(e)}"
                )

            # Return JWT
            refresh = RefreshToken.for_user(user)
            return Response({
                "success": True,
                "message": "User created successfully",
                "user_id": user.id,
                "role": user.role,
                "username": user.username,
                "access": str(refresh.access_token),
                "refresh": str(refresh)
                
            }, status=status.HTTP_201_CREATED)
        print(serializer.errors)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

#Forgot Password View
class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):

        email = request.data.get("email")

        if not email:
            return Response(
                {"error": "Email is required"},
                status=400
            )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {"error": "User not found"},
                status=404
            )

        otp = str(random.randint(100000, 999999))

        PasswordResetOTP.objects.filter(user=user).delete()

        PasswordResetOTP.objects.create(
            user=user,
            otp=otp
        )

        send_email(
            subject="Password Reset OTP",
            message=f"""
Your Senmi password reset code is:

{otp}

This code expires in 10 minutes.
            """,
            recipients=[email]
        )

        return Response({
            "success": True,
            "message": "OTP sent successfully"
        })
    
    

#Reset Password View
class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):

        email = request.data.get("email")
        otp = request.data.get("otp")
        password = request.data.get("password")

        if not all([email, otp, password]):
            return Response(
                {"error": "Email, OTP and password are required"},
                status=400
            )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {"error": "User not found"},
                status=404
            )

        try:
            reset = PasswordResetOTP.objects.get(
                user=user,
                otp=otp
            )
        except PasswordResetOTP.DoesNotExist:
            return Response(
                {"error": "Invalid OTP"},
                status=400
            )

        if reset.is_expired():
            reset.delete()

            return Response(
                {"error": "OTP expired"},
                status=400
            )

        validate_password(password)

        user.set_password(password)
        user.save()

        reset.delete()

        return Response({
            "success": True,
            "message": "Password updated successfully"
        })
    


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
    permission_classes = [IsAdminOrSupport]

    def get(self, request):
        riders = RiderProfile.objects.select_related('user').all()
        data = [{
            "id": r.id,
            "rider_id": r.rider_id,
            "username": r.user.username,
            "email": r.user.email,
            "status": r.status,
            "phone": r.phone_number,
            "city": r.city,
            "address": r.address,
            "profile_picture": r.profile_picture.url if r.profile_picture else None,
            "rider_image_1": r.rider_image_1.url if r.rider_image_1 else None,
            "rider_image_with_vehicle": r.rider_image_with_vehicle.url if r.rider_image_with_vehicle else None,
        } for r in riders]

        paginator = StandardPagination()
        result = paginator.paginate_queryset(data, request)
        return paginator.get_paginated_response(result)


class AdminUserSearchView(APIView):
    permission_classes = [IsAdminOrSupport]

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


class AdminPackagesView(APIView):
    permission_classes = [IsAdminOrSupport]

    def get(self, request):
        packages = Package.objects.select_related(
            'customer',
            'rider'
        ).all().order_by('-created_at')

        serializer = PackageSerializer(
            packages,
            many=True,
            context={"request": request}
        )

        return Response(serializer.data)
    


@api_view(['GET'])
@permission_classes([IsAdminOrSupport])
def admin_customers(request):

    customers = (
        User.objects.filter(role='customer')
        .annotate(
            total_packages=Count('orders'),
            total_spent=Sum('orders__price')
        )
        .order_by('-date_joined')
    )

    results = []

    for customer in customers:
        results.append({
            "id": customer.id,
            "user_id": customer.user_id,
            "username": customer.username,
            "email": customer.email,
            "phone_number": customer.phone_number,
            "date_joined": customer.date_joined,
            "total_packages": customer.total_packages,
            "total_spent": customer.total_spent or 0,
        })

    return Response(results)


@api_view(['GET'])
@permission_classes([IsAdminOrSupport])
def admin_customer_detail(request, customer_id):

    try:
        customer = User.objects.get(
            id=customer_id,
            role='customer'
        )

    except User.DoesNotExist:
        return Response(
            {"error": "Customer not found"},
            status=404
        )

    packages = Package.objects.filter(customer=customer)

    delivered = packages.filter(status='delivered').count()
    pending = packages.filter(status='pending').count()
    paid = packages.filter(status='paid').count()
    cancelled = packages.filter(status='cancelled').count()

    total_spent = packages.aggregate(
        total=Sum('price')
    )['total'] or 0

    recent_packages = packages.order_by(
        '-created_at'
    )[:10]

    package_data = []

    for p in recent_packages:
        package_data.append({
            "package_id": p.package_id,
            "description": p.description,
            "status": p.status,
            "price": p.price,
            "created_at": p.created_at,
            "pickup_lat": p.pickup_lat,
            "pickup_lng": p.pickup_lng,
            "delivery_lat": p.delivery_lat,
            "delivery_lng": p.delivery_lng,
        })

    return Response({
        "id": customer.id,
        "user_id": customer.user_id,
        "username": customer.username,
        "email": customer.email,
        "phone_number": customer.phone_number,
        "date_joined": customer.date_joined,
        "last_login": customer.last_login,

        "total_packages": packages.count(),
        "delivered_packages": delivered,
        "pending_packages": pending,
        "paid_packages": paid,
        "cancelled_packages": cancelled,

        "total_spent": total_spent,

        "recent_packages": package_data,
    })



class AvailableRidersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):

        riders = RiderProfile.objects.filter(
            status='approved'
        )

        data = []

        for rider in riders:
            data.append({
                "id": rider.user.id,
                "name": rider.user.username,
            })

        return Response(data)
    

@api_view(['GET'])
@permission_classes([IsAdminOrSupport])
def admin_analytics(request):

    packages = Package.objects.all()

    total_deliveries = packages.count()

    completed_deliveries = packages.filter(
        status='delivered'
    ).count()

    failed_deliveries = packages.filter(
        status='cancelled'
    ).count()

    total_revenue = packages.aggregate(
        total=Sum('price')
    )['total'] or 0

    total_rider_payout = packages.aggregate(
        total=Sum('rider_earning')
    )['total'] or 0

    # =========================
    # AVERAGE DELIVERY TIME
    # =========================

    delivered_packages = packages.filter(
        status='delivered',
        delivered_at__isnull=False
    )

    avg_duration = delivered_packages.annotate(
        duration=ExpressionWrapper(
            F('delivered_at') - F('created_at'),
            output_field=DurationField()
        )
    ).aggregate(
        avg=Avg('duration')
    )['avg']

    average_delivery_time = str(avg_duration) if avg_duration else "0"

    # =========================
    # DELIVERY SUCCESS RATE
    # =========================

    delivery_success_rate = 0

    if total_deliveries > 0:
        delivery_success_rate = round(
            (completed_deliveries / total_deliveries) * 100,
            2
        )

    # =========================
    # ACTIVE RIDERS
    # =========================

    active_riders = RiderProfile.objects.filter(
        status='approved'
    ).count()

    # =========================
    # CUSTOMERS
    # =========================

    total_customers = User.objects.filter(
        role='customer'
    ).count()

    # =========================
    # FREQUENT CUSTOMERS
    # =========================

    top_customers = (
        User.objects.filter(role='customer')
        .annotate(total_orders=Count('orders'))
        .order_by('-total_orders')[:5]
        .values('username', 'total_orders')
    )

    # =========================
    # TOP RIDERS
    # =========================

    top_riders = (
        User.objects.filter(role='rider')
        .annotate(total_deliveries=Count('deliveries'))
        .order_by('-total_deliveries')[:5]
        .values('username', 'total_deliveries')
    )

    daily_revenue = (
        Package.objects.filter(status='delivered')
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(total=Sum('price'))
        .order_by('day')
    )

    monthly_deliveries = (
        Package.objects.filter(status='delivered')
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(total=Count('id'))
        .order_by('month')
    )

    peak_hours = (
        Package.objects
        .annotate(hour=ExtractHour('created_at'))
        .values('hour')
        .annotate(total=Count('id'))
        .order_by('-total')[:5]
    )

    heatmap_data = Package.objects.filter(
        delivery_lat__isnull=False,
        delivery_lng__isnull=False,
    ).values(
        'delivery_lat',
        'delivery_lng'
    )

    pending_withdrawals = Withdrawal.objects.filter(
        status='pending'
    ).aggregate(
        total=Sum('amount')
    )['total'] or 0

    failure_stats = (
        Package.objects
        .exclude(failure_reason='')
        .values('failure_reason')
        .annotate(total=Count('id'))
    )



    data = {
        "total_deliveries": total_deliveries,
        "completed_deliveries": completed_deliveries,
        "failed_deliveries": failed_deliveries,
        "total_revenue": total_revenue,
        "total_rider_payout": total_rider_payout,
        "average_delivery_time": average_delivery_time,

        # NEW
        "delivery_success_rate": delivery_success_rate,
        "active_riders": active_riders,
        "total_customers": total_customers,
        "top_customers": list(top_customers),
        "top_riders": list(top_riders),
        "daily_revenue": list(daily_revenue),
        "monthly_deliveries": list(monthly_deliveries),
        "peak_hours": list(peak_hours),
        "heatmap_data": list(heatmap_data),
        "pending_withdrawals": pending_withdrawals,
        "failure_stats": list(failure_stats),
    }

    return Response(data)



@api_view(['GET'])
@permission_classes([IsAdminOrSupport])
def admin_dashboard(request):

    total_riders = RiderProfile.objects.count()

    pending_riders = RiderProfile.objects.filter(
        status='pending'
    ).count()

    active_deliveries = Package.objects.filter(
        status__in=['accepted', 'picked_up']
    ).count()

    completed_deliveries = Package.objects.filter(
        status='delivered'
    ).count()

    # IMPORTANT: define clearly what "available" means
    available_packages = Package.objects.exclude(
        status='delivered'
    ).count()

    wallet_count = RiderWallet.objects.count()

    pending_withdrawals = Withdrawal.objects.filter(
        status="processing"
    ).count()

    # =========================
    # ALERTS
    # =========================
    alerts = []

    if pending_riders > 0:
        alerts.append(f"{pending_riders} riders awaiting approval")

    failed_today = Package.objects.filter(
        status='cancelled'
    ).count()

    if failed_today > 5:
        alerts.append(f"{failed_today} deliveries cancelled recently")

    pending_withdrawals = Withdrawal.objects.filter(
        status='pending'
    ).count()

    if pending_withdrawals > 0:
        alerts.append(f"{pending_withdrawals} withdrawals pending")

    # 🚨 ADD IMPORTANT SYSTEM ALERTS
    if active_deliveries > 50:
        alerts.append("High delivery load detected")

    data = {
    "total_riders": total_riders,
    "pending_riders": pending_riders,
    "active_deliveries": active_deliveries,
    "completed_deliveries": completed_deliveries,
    "available_packages": available_packages,

    "wallet_count": wallet_count,
    "pending_withdrawals": pending_withdrawals,

    "alerts": alerts,
}

    return Response(data)



@api_view(['POST'])
@permission_classes([IsAdminOrSupport])
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

    # LIVE ADMIN DASHBOARD UPDATE
    notify_admin_dashboard()

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

    send_fcm_notification(
        profile.user,
        "Account Review",
        "Your rider profile has been reviewed",
        {"type": "account_review", "status": status_value}
    )

    recipients = [settings.NOTIFY_EMAIL, profile.user.email]

    send_email(subject="Rider Profile Review", message=message, recipients=recipients)

    return Response({"message": f"Rider profile {status_value} successfully."}, status=200)



from .models import Notification

class AdminNotificationView(APIView):
    permission_classes = [IsAdminOrSupport]

    def post(self, request):
        title = request.data.get("title")
        body = request.data.get("body")
        target = request.data.get("target", "all")
        user_id = request.data.get("user_id", None)

        if not title or not body:
            return Response({"error": "title and body required"}, status=400)

        data = {
            "type": "admin_message",
            "title": title,
            "body": body
        }

        # =========================
        # SELECT USERS
        # =========================
        if target == "single":
            users = User.objects.filter(id=user_id)

        elif target == "riders":
            users = User.objects.filter(role="rider")

        elif target == "customers":
            users = User.objects.filter(role="customer")

        else:
            users = User.objects.all()

        # =========================
        # SEND + SAVE (NO DUPLICATES)
        # =========================
        created_count = 0

        with transaction.atomic():
            for user in users.distinct():

                # 🔥 prevent duplicate DB spam
                exists = Notification.objects.filter(
                    user=user,
                    message=body,
                    type="admin_message"
                ).exists()

                if exists:
                    continue

                send_fcm_notification(
                    user=user,
                    title=title,
                    body=body,
                    data=data
                )

                Notification.objects.create(
                    user=user,
                    message=body,
                    type="admin_message"
                )

                created_count += 1

        return Response({
            "success": True,
            "target": target,
            "count": created_count
        })
    



from django.core.paginator import Paginator

@api_view(['GET'])
@permission_classes([IsAdminOrSupport])
def admin_notifications(request):

    page = int(request.GET.get("page", 1))
    limit = int(request.GET.get("limit", 20))

    qs = Notification.objects.all().order_by("-created_at")

    paginator = Paginator(qs, limit)
    page_obj = paginator.get_page(page)

    return Response({
        "results": [
            {
                "id": n.id,
                "message": n.message,
                "user": n.user.username if n.user else "All Users",
                "created_at": n.created_at,
            }
            for n in page_obj.object_list
        ],
        "has_next": page_obj.has_next(),
        "page": page,
    })

  

from django.db import IntegrityError

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_fcm_token(request):
    token = request.data.get("token")
    device_type = request.data.get("device_type", "android")

    user = request.user

    if not token:
        return Response({"error": "Token required"}, status=400)

    try:
        # Find existing token first
        device = FCMDevice.objects.filter(token=token).first()

        if device:
            # Update existing device ownership
            device.user = user
            device.device_type = device_type
            device.is_active = True
            device.save()

            created = False

        else:
            # Create new token
            device = FCMDevice.objects.create(
                user=user,
                token=token,
                device_type=device_type,
                is_active=True,
            )

            created = True

        return Response({
            "success": True,
            "created": created
        })

    except IntegrityError:
        return Response({
            "error": "Token conflict"
        }, status=409)

    except Exception as e:
        return Response({
            "error": str(e)
        }, status=500)


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
            
            send_fcm_notification(
                request.user,
                "Profile Submitted",
                "Your rider profile has been submitted and is awaiting admin review.",
                {"type": "rider_profile_pending"}
            )

            try:
                # Send to rider + your notify email ONLY
                recipients = [request.user.email, settings.NOTIFY_EMAIL]
                recipients = [r for r in recipients if r]

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
            status='paid',          
            is_paid=True,           
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

                """PackageStatusHistory.objects.create(
                    package=package,
                    status='accepted'
                )"""

                # =========================
                # 🔔 NOTIFY OTHER RIDERS
                # =========================
                try:
                    notify_admin_dashboard()
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

                """send_email(
                    subject=" Package Accepted",
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
                )"""
                send_fcm_notification(
                    package.customer,
                    "Package Accepted",
                    f"Rider accepted your package {package.package_id}",
                    {"type": "package_accepted"}
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
            #'description',
            'pickup_address',
            'delivery_address',
            #'receiver_name',
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
                """recipients = [request.user.email] + [settings.NOTIFY_EMAIL]

                send_email(
                    subject="Package Created",
                    message=(
                        f"Hello {request.user.username},\n\n"
                        f"Your package {package.package_id} has been created successfully.\n\n"
                        f"Please proceed to payment so a rider can accept your delivery.\n\n"
                        f"Thank you for using Senmi."
                    ),
                    recipients=recipients
                )"""

                send_fcm_notification(
                    request.user,
                    "Package Created",
                    f"Package {package.package_id} created successfully",
                    {"type": "package_created"}
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

                # ADDED CANCEL (NOT CHANGING ANYTHING ELSE)
                if new_status in ["cancelled", "canceled", "cancel"]:

                    if package.status != "accepted":
                        return Response({
                            "success": False,
                            "error": "Cancellation only allowed when package is accepted"
                        }, status=400)

                    rider_user = request.user
                    rider_profile = getattr(rider_user, 'riderprofile', None)
                    rider_id = rider_profile.rider_id if rider_profile else "N/A"

                    
                    package.failure_reason = request.data.get('failure_reason', '')
                    package.status = "paid"
                    package.rider = None
                    package.save()

                    notify_admin_dashboard()
                     
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
                        "message": "Package released and returned to available deliveries"
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

                try:
                    channel_layer = get_channel_layer()

                    async_to_sync(channel_layer.group_send)(
                        "admin_dashboard",
                        {
                            "type": "dashboard_update",
                            "message": "refresh"
                        }
                    )

                except Exception as e:
                    logger.exception(
                        f"Dashboard websocket failed: {e}"
                    )



                # ✅ save delivery completion time
                if new_status == "delivered" and not package.delivered_at:
                    package.delivered_at = now()

                package.save()

               
                #PackageStatusHistory.objects.create(package=package, status=new_status)
                try:
                    notify_admin_dashboard()
                except Exception as e:
                    logger.exception(f"WebSocket broadcast failed (status update): {e}")

                # Send email after transaction
                recipients = [package.customer.email, package.rider.email] + [settings.NOTIFY_EMAIL]
                recipients = [r for r in recipients if r]

                try:

                    if new_status == "picked_up":

                        send_fcm_notification(
                            package.customer,
                            "Package Picked Up",
                            f"Your package {package.package_id} has been picked up",
                            {"type": "picked_up"}
                        )

                    elif new_status == "delivered":

                        send_fcm_notification(
                            package.customer,
                            "Delivered",
                            f"Package {package.package_id} delivered successfully",
                            {"type": "delivered"}
                        )

                        # ONLY SEND EMAIL FOR DELIVERED
                        message = (
                            f"Hello {package.customer.username},\n\n"
                            f"Your package {package.package_id} has been successfully delivered.\n\n"
                            f"We hope you had a great experience.\n\n"
                            f"Thank you for using Senmi."
                        )

                        send_email(
                            subject=f"Package Delivered - {package.package_id}",
                            message=message,
                            recipients=recipients
                        )

                    else:

                        send_fcm_notification(
                            package.customer,
                            "Package Update",
                            f"Package {package.package_id} is now {new_status}",
                            {"type": new_status}
                        )

                except Exception as e:
                    logger.exception(
                        f"Failed to send status update notification for package {package.package_id}: {e}"
                    )
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

        # PACKAGE ALREADY PAID
       
        if package.is_paid:
            return Response({
                "already_paid": True,
                "message": "Payment has already been made for this package."
            }, status=200)


        
        # PAYMENT LINK ALREADY EXISTS
     
        if package.payment_initialized and package.payment_reference:

            if package.is_paid:
                return Response({
                    "already_paid": True,
                    "message": "Payment has already been made for this package."
                }, status=200)

            verify_url = f"https://api.paystack.co/transaction/verify/{package.payment_reference}"

            verify_res = requests.get(
                verify_url,
                headers={
                    "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"
                },
                timeout=10
            )

            verify_data = verify_res.json()

            
            # PAYMENT SUCCESSFUL
            if (
                verify_data.get("status")
                and verify_data["data"]["status"] == "success"
            ):

                package.is_paid = True
                package.status = "paid"
                package.payment_completed_at = timezone.now()

                package.save(update_fields=[
                    "is_paid",
                    "status",
                    "payment_completed_at"
                ])

                return Response({
                    "already_paid": True,
                    "message": "Payment has already been made for this package."
                })

       
            # PAYMENT STILL PENDING
            return Response({
                "payment_url": package.payment_url,
                "message": "Existing payment link reused."
            })
        
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
            "callback_url": settings.PAYMENT_CALLBACK_URL,
            "metadata": {
                "package_id": package.package_id
            }
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

            # FIXED: always overwrite old reference safely
            package.payment_reference = res_data["data"]["reference"]

            package.payment_url = res_data["data"]["authorization_url"]

            package.payment_initialized = True

            package.save(update_fields=[
                'payment_reference',
                'payment_url',
                'payment_initialized'
            ])

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
                package.payment_completed_at = timezone.now()

                package.save(update_fields=[
                    "is_paid",
                    "status",
                    "payment_completed_at"
                ])

              
                notify_admin_dashboard()
                logger.info(f"Package {package.id} marked as paid via webhook.")

            
        except Package.DoesNotExist:
            logger.warning(f"No package found with payment reference {reference}")
            return Response(status=200)

        except Exception as e:
            logger.exception(f"Error processing Paystack webhook for reference {reference}")
            return Response(status=500)

        return Response(status=200)
    


class PaymentCallbackView(APIView):
    def get(self, request):
        reference = request.GET.get("reference")

        if not reference:
            return Response({"error": "No reference"}, status=400)

        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"
        }

        verify = requests.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers=headers
        ).json()

        if not verify.get("status"):
            return Response({"error": "Verification failed"}, status=400)

        data = verify["data"]

        if data["status"] != "success":
            return Response({"error": "Payment not successful"}, status=400)

        try:
            with transaction.atomic():
                package = Package.objects.select_for_update().get(
                    payment_reference=reference
                )

                if package.is_paid:
                    return Response({
                        "message": "Package already paid"
                    })
                

                package.is_paid = True
                package.status = "paid"
                package.payment_completed_at = timezone.now()

                package.save(update_fields=[
                    "is_paid",
                    "status",
                    "payment_completed_at"
                ])

                notify_admin_dashboard()

                # CUSTOMER EMAIL
                try:
                    send_email(
                        subject="Payment Successful",
                        message=(
                            f"Hello {package.customer.username},\n\n"
                            f"Your payment for package {package.package_id} was successful.\n\n"
                            f"Delivery Code: {package.delivery_code}\n\n"
                            f"Please share this code ONLY with the rider upon delivery.\n\n"
                            f"Your package is now available for riders to accept.\n\n"
                            f"Thank you for using Senmi."
                        ),
                        recipients=[package.customer.email]
                    )
                except Exception as e:
                    logger.exception(f"Customer email failed: {e}")


                try:
                    send_email(
                        subject="Customer Paid for Package",
                        message=(
                            f"A customer has successfully paid.\n\n"
                            f"Package ID: {package.package_id}\n"
                            f"Customer: {package.customer.username}\n"
                            f"Customer Email: {package.customer.email}\n"
                            f"Pickup: {package.pickup_address}\n"
                            f"Delivery: {package.delivery_address}\n"
                            f"Amount: ₦{package.price}\n"
                            f"Status: {package.status}\n"
                            f"Delivery Code: {package.delivery_code}\n"
                        ),
                        recipients=[settings.NOTIFY_EMAIL]
                    )
                except Exception as e:
                    logger.exception(f"Admin email failed: {e}")

             # =====================================
                # PUSH NOTIFICATION TO CUSTOMER
                # =====================================
                send_fcm_notification(
                    user=package.customer,
                    title="Payment Successful",
                    body=f"Your payment for package {package.package_id} was successful.",
                    data={
                        "type": "payment_success",
                        "package_id": package.package_id
                    }
                )
                # PUSH NOTIFICATION TO RIDERS
               
                approved_riders = User.objects.filter(
                    role="rider",
                    riderprofile__status="approved"
                )

                for rider in approved_riders:
                    send_fcm_notification(
                        user=rider,
                        title="New Delivery Available",
                        body=f"New package from {package.pickup_address}",
                        data={
                            "type": "new_package",
                            "package_id": package.package_id,
                            "pickup": package.pickup_address,
                            "delivery": package.delivery_address,
                        }
                    )

        except Package.DoesNotExist:
            return Response({"error": "Package not found"}, status=404)
        
        if package.is_paid:
            return redirect(
                f"https://www.senmi.com.ng/api/payment-success/"
                f"?package_id={package.package_id}"
                f"&delivery_code={package.delivery_code}"
            )



def payment_success(request):
    package_id = request.GET.get("package_id", "")
    delivery_code = request.GET.get("delivery_code", "")

    return HttpResponse(f"""
    <html>
    <head>
        <title>Payment Successful</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
    </head>

    <body style="
        display:flex;
        justify-content:center;
        align-items:center;
        height:100vh;
        font-family:sans-serif;
        flex-direction:column;
        background:#f5f5f5;
    ">

        <h1 style="color:green;">Payment Successful</h1>

        <p>Your package payment was completed successfully.</p>

        <button
            onclick="window.location.href='senmi://payment-success?package_id={package_id}&delivery_code={delivery_code}'"
            style="
                padding:14px 24px;
                border:none;
                background:green;
                color:white;
                border-radius:8px;
                font-size:16px;
            "
        >
            Continue
        </button>

    </body>
    </html>
    """)


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



def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c


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
        remaining_km = calculate_distance(
        tracking.latitude,
        tracking.longitude,
        package.delivery_lat,
        package.delivery_lng
        )

        eta_minutes = round(remaining_km * 4)

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
            "eta_minutes": eta_minutes,
            
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

        if amount > wallet.balance:
            return Response(
                {"error": "Insufficient balance"},
                status=400
            )

        bank_account = request.data.get('bank_account')
        bank_code = request.data.get('bank_code')

        if not bank_account or not bank_code:
            return Response({"error": "Bank details required"}, status=400)

        withdrawal = Withdrawal.objects.create(
            rider=request.user,
            amount=amount,
            bank_account=bank_account,
            bank_code=bank_code,
            status="processing"
        )
        notify_admin_dashboard()

        send_fcm_notification(
            request.user,
            "Withdrawal Processing",
            "Your withdrawal is being processed",
            {"type": "withdrawal_processing"}
        )

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
            withdrawal.status = "failed"
            withdrawal.failure_reason = str(e)
            withdrawal.save()

            return Response({
                "error": "Verification request failed",
                "details": str(e)
            }, status=500)

        if not verify_json.get("status"):
            withdrawal.status = "failed"
            withdrawal.failure_reason = verify_json.get("message")
            withdrawal.save()

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
            withdrawal.status = "failed"
            withdrawal.failure_reason = recipient_res.get("message")
            withdrawal.save()

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

            send_fcm_notification(
                request.user,
                "Withdrawal Failed",
                transfer_res.get("message"),
                {"type": "withdrawal_failed"}
            )

            return Response({
                "error": "Transfer failed",
                "paystack_message": transfer_res.get("message"),
                "details": transfer_res
            }, status=400)

        # ✅ SUCCESS
        wallet.balance -= amount
        wallet.save()

        withdrawal.status = "success"
        withdrawal.save()

        # ✅ LIVE ADMIN DASHBOARD UPDATE
        channel_layer = get_channel_layer()

        async_to_sync(channel_layer.group_send)(
            "admin_dashboard",
            {
                "type": "dashboard_update",
                "message": "refresh"
            }
        )

        send_fcm_notification(
            request.user,
            "Withdrawal Successful",
            "Withdrawal successful",
            {"type": "withdrawal_success"}
        )

        return Response({
            "message": "Withdrawal successful"
        })
    

class AdminWithdrawalsView(APIView):
    permission_classes = [IsAdminOrSupport]

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
    


class AdminRiderWalletView(APIView):
    permission_classes = [IsAdminOrSupport]

    def get(self, request):
        wallets = RiderWallet.objects.select_related("rider").all()

        data = [
            {
                "rider_id": w.rider.id,
                "email": w.rider.email,
                "balance": float(w.balance),
                "total_earned": float(w.total_earned),
            }
            for w in wallets
        ]

        return Response(data)
    

class ApproveWithdrawalView(APIView):
    permission_classes = [IsAdminOrSupport]

    def post(self, request, withdrawal_id):
        withdrawal = get_object_or_404(Withdrawal, id=withdrawal_id)

        if withdrawal.status not in ["pending", "processing"]:
            return Response(
                {"error": "Cannot approve this withdrawal"},
                status=400
            )

        withdrawal.status = "approved"
        withdrawal.save()

        notify_admin_dashboard()

        send_fcm_notification(
            withdrawal.rider.user,
            "Withdrawal Approved",
            "Your withdrawal has been approved",
            {"type": "withdrawal_approved"}
        )

        return Response({
            "message": "Withdrawal approved"
        })
        

class RejectWithdrawalView(APIView):
    permission_classes = [IsAdminOrSupport]

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

        notify_admin_dashboard()

        send_fcm_notification(
            withdrawal.rider.user,
            "Withdrawal Rejected",
            withdrawal.failure_reason,
            {"type": "withdrawal_rejected"}
        )

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
    permission_classes = [IsAdminOrSupport]

    def post(self, request, withdrawal_id):
        withdrawal = get_object_or_404(Withdrawal, id=withdrawal_id)

        if withdrawal.status != "failed":
            return Response(
                {"error": "Only failed withdrawals can be retried"},
                status=400
            )

        # 🔄 mark retry started
        withdrawal.status = "processing"
        withdrawal.failure_reason = None
        withdrawal.save()
        notify_admin_dashboard()
        # notify rider
        send_fcm_notification(
            withdrawal.rider.user,
            "Withdrawal Retry",
            "Your withdrawal is being retried",
            {"type": "withdrawal_retry"}
        )

        # run actual payout logic
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
    notify_admin_dashboard()
    send_fcm_notification(
        withdrawal.rider.user,
        "Withdrawal Successful",
        "Withdrawal successful",
        {"type": "withdrawal_success"}
    )


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
    