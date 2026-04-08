import random
import uuid
import hashlib
import hmac
import json
import logging
import requests
from decimal import Decimal, InvalidOperation
import re
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.db import IntegrityError, transaction
from django.db.models import Q, Avg, Count, Prefetch
from django.contrib.auth import authenticate
from .utils import send_email, calculate_distance
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated, IsAdminUser
from rest_framework.decorators import api_view, permission_classes
from rest_framework.throttling import UserRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from .utils import calculate_distance, calculate_price
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from .models import (
    Package, PackageStatusHistory, PackageTracking,
    RiderRating, RiderWallet, RiderProfile
)
from .serializers import (
    RegisterSerializer, RiderProfileSerializer, CustomLoginSerializer,
    PackageSerializer
)
from senmi.models import User
from senmi.utils import send_email



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
# Authentication / Login
# ------------------------------
class CustomLoginView(TokenObtainPairView):
    serializer_class = CustomLoginSerializer


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
            "role": user.role,
            "username": user.username,
            "is_admin": user.is_superuser
        })


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
        return Response(data)


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

    message = f"Your rider profile has been {'approved' if status_value == 'approved' else f'rejected: {reason}'}"

    # Send to rider + admins + your Gmail
    admins = list(User.objects.filter(is_superuser=True).values_list('email', flat=True))
    recipients = admins + [settings.NOTIFY_EMAIL, profile.user.email]

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
                admin_emails = list(User.objects.filter(is_superuser=True).values_list('email', flat=True))
                recipients = [user.email] + admin_emails + [settings.NOTIFY_EMAIL]
                send_email(
                    subject="Welcome to SenMi!",
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
                "access": str(refresh.access_token)
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
                send_email(
                    subject="Rider Profile Submitted",
                    message=f"Hello {request.user.username}, your rider profile (ID: {profile.rider_id}) has been submitted successfully and is pending admin review.",
                    recipients=[request.user.email]
                )
                admins = list(User.objects.filter(is_superuser=True).values_list('email', flat=True))
                if admins:
                    send_email(
                        subject="New Rider Profile Pending Review",
                        message=f"A new rider profile has been submitted.\nUser: {request.user.username}\nEmail: {request.user.email}\nRider ID: {profile.rider_id}\nStatus: PENDING",
                        recipients=admins + [settings.NOTIFY_EMAIL]
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
            status='pending',
            rider__isnull=True,
            pickup_address__icontains=rider_city,
            pickup_lat__isnull=False
        ).order_by('-created_at')

        data = []
        for p in packages:
            # Calculate net earning dynamically
            net_earning = float(p.rider_earning - p.commission)
            data.append({
                "id": p.id,
                "description": p.description,
                "pickup": p.pickup_address,
                "delivery": p.delivery_address,
                "price": float(p.price),
                "receiver_name": p.receiver_name,
                "receiver_phone": p.receiver_phone,
                "commission": float(p.commission),
                "rider_earning": float(p.rider_earning),
                "net_earning": max(net_earning, 0)  # never negative
            })

        return Response(data)



class AcceptPackageView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def post(self, request, package_id):
        try:
            with transaction.atomic():
                package = Package.objects.select_for_update().get(id=package_id)

                if request.user.role != 'rider':
                    return Response({"error": "Only riders can accept"}, status=403)
                if package.payment_type == "sender" and not package.is_paid:
                    return Response({"error": "Sender has not paid"}, status=400)
                if package.status != 'pending':
                    return Response({"error": "Package not available"}, status=400)

                package.rider = request.user
                package.status = 'accepted'
                package.save()
                PackageStatusHistory.objects.create(package=package, status='accepted')

                # ✅ NEW: BROADCAST PACKAGE TAKEN
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
                    logger.exception(f"WebSocket broadcast failed (accept package): {e}")

                # Send email BEFORE returning
                admin_emails = list(User.objects.filter(is_superuser=True).values_list('email', flat=True))
                recipients = [package.customer.email, request.user.email] + admin_emails + [settings.NOTIFY_EMAIL]
                recipients = [r for r in recipients if r]

                try:
                    send_email(
                        subject="Package Accepted",
                        message=f"Package {package.package_id} has been accepted by rider {request.user.username}.",
                        recipients=recipients
                    )
                except Exception as e:
                    logger.exception(f"Failed to send package acceptance email: {e}")

            net_earning = float(package.rider_earning - package.commission)
            return Response({
                "message": "Accepted successfully",
                "net_earning": net_earning
            }, status=200)

        except Package.DoesNotExist:
            return Response({"error": "Package not found"}, status=404)
        except Exception as e:
            logger.exception(f"Error accepting package {package_id}: {e}")
            return Response({"error": "Failed to accept package"}, status=500)
        



# ------------------------------
# Package Management Views
# ------------------------------
class CreatePackageView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != 'customer':
            return Response({"error": "Only customers can create packages"}, status=403)

        # Get coordinates from request
        try:
            pickup_lat = float(request.data.get('pickup_lat'))
            pickup_lng = float(request.data.get('pickup_lng'))
            delivery_lat = float(request.data.get('delivery_lat'))
            delivery_lng = float(request.data.get('delivery_lng'))
        except (TypeError, ValueError):
            return Response({"error": "Invalid or missing coordinates"}, status=400)

        # Calculate distance and dynamic price
        distance = calculate_distance(pickup_lat, pickup_lng, delivery_lat, delivery_lng)
        dynamic_price = calculate_price(distance)

        # Override price in request data
        data = request.data.copy()
        data['price'] = dynamic_price

        serializer = PackageSerializer(data=data)
        if serializer.is_valid():
            package = serializer.save(customer=request.user)
            # Commission and rider_earning already handled in Package.save()

            # Generate delivery code if receiver pays
            if package.payment_type == "receiver" and not package.delivery_code:
                package.delivery_code = str(random.randint(100000, 999999))
                package.save(update_fields=['delivery_code'])

            # Broadcast to riders
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
                logger.exception(f"WebSocket broadcast failed (create package): {e}")

            # Send emails
            admin_emails = list(User.objects.filter(is_superuser=True).values_list('email', flat=True))
            recipients = [request.user.email] + admin_emails + [settings.NOTIFY_EMAIL]
            send_email(
                subject=f"New Package Created",
                message=(
                    f"Package {package.package_id} has been created by {request.user.username}.\n"
                    f"Description: {package.description}\nPrice: {package.price}\nStatus: {package.status}"
                ),
                recipients=recipients
            )

            return Response({
                **serializer.data,
                "package_id": package.package_id,
                "delivery_code": package.delivery_code,
                "commission": package.commission,
                "rider_earning": package.rider_earning
            }, status=201)

        return Response(serializer.errors, status=400)
    



class UpdateDeliveryStatusView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def post(self, request, package_id):
        try:
            with transaction.atomic():
                package = Package.objects.select_for_update().get(id=package_id)

                if package.rider != request.user:
                    return Response({"error": "Not your package"}, status=403)

                new_status = request.data.get('status')
                valid_flow = {'accepted': 'picked_up', 'picked_up': 'delivered'}

                if package.status not in valid_flow:
                    return Response({"error": "Invalid current status"}, status=400)

                if new_status != valid_flow[package.status]:
                    return Response({"error": "Invalid status transition"}, status=400)

                # Final delivery handling
                if new_status == "delivered":
                    code_input = request.data.get('delivery_code')
                    if not code_input or package.delivery_code != code_input:
                        return Response({"error": "Invalid or missing delivery code"}, status=400)

                    wallet, _ = RiderWallet.objects.select_for_update().get_or_create(rider=request.user)

                    # Always subtract commission from rider earnings
                    net_earning = package.rider_earning - package.commission
                    if net_earning < 0:
                        return Response({"error": "Earnings cannot be negative"}, status=400)

                    wallet.deposit(net_earning)
                    wallet.save()

                    # Mark collected if payment type is receiver
                    if package.payment_type == "receiver" and not package.is_collected:
                        package.is_collected = True
                        package.save(update_fields=['is_collected'])

                package.status = new_status
                package.save()

                # ✅ KEEP YOUR HISTORY (unchanged)
                PackageStatusHistory.objects.create(package=package, status=new_status)

                # ✅ NEW: BROADCAST STATUS UPDATE (correct position)
                try:
                    channel_layer = get_channel_layer()
                    async_to_sync(channel_layer.group_send)(
                        f"tracking_{package.id}",  # 👈 matches your existing consumer
                        {
                            "type": "send_location",  # 👈 reuse existing handler
                            "lat": 0,  # dummy (optional)
                            "lng": 0,
                            "status": new_status  # 👈 NEW FIELD
                        }
                    )
                except Exception as e:
                    logger.exception(f"WebSocket broadcast failed (status update): {e}")

                # Send email after transaction
                admin_emails = list(User.objects.filter(is_superuser=True).values_list('email', flat=True))
                recipients = [package.customer.email, package.rider.email] + admin_emails + [settings.NOTIFY_EMAIL]
                recipients = [r for r in recipients if r]

                try:
                    send_email(
                        subject=f"Package {package.package_id} Status Update",
                        message=f"Package {package.package_id} is now {new_status}.",
                        recipients=recipients
                    )
                except Exception as e:
                    logger.exception(f"Failed to send status update email for package {package.package_id}: {e}")

                return Response({"message": f"Package marked as {new_status}"})

        except Package.DoesNotExist:
            return Response({"error": "Package not found"}, status=404)
        except Exception as e:
            logger.exception(f"Error updating package status {package_id}: {e}")
            return Response({"error": "Failed to update package status"}, status=500)
        




class RiderActivePackagesView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def get(self, request):
        packages = Package.objects.filter(rider=request.user).order_by('-created_at')

        data = []
        for p in packages:
            data.append({
                "id": p.id,
                "status": p.status,
                "pickup": p.pickup_address,
                "delivery": p.delivery_address,
                "net_earning": float(p.rider_earning - p.commission),
            })

        return Response(data)
    


class RiderEarningsView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def get(self, request):
        # Only delivered packages
        deliveries = Package.objects.filter(rider=request.user, status='delivered')

        # Calculate net earnings after subtracting commission
        total_earnings = sum((p.rider_earning - p.commission) for p in deliveries)

        return Response({
            "total_earnings": total_earnings,
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
            package = Package.objects.select_for_update().get(id=package_id)
        except Package.DoesNotExist:
            return Response({"error": "Package not found"}, status=404)

        if package.payment_type != "receiver":
            return Response({"error": "Invalid payment attempt"}, status=400)

        if package.is_paid:
            return Response({"message": "Package already paid"}, status=200)

        receiver_email = request.data.get("receiver_email") or package.receiver_email
        if not receiver_email or not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", receiver_email):
            return Response({"error": "Valid receiver email required"}, status=400)

        url = "https://api.paystack.co/transaction/initialize"
        headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}
        data = {
            "email": receiver_email,
            "amount": int(Decimal(package.price) * 100),
            "reference": package.payment_reference or f"PKG-{package.id}-{uuid.uuid4().hex[:6]}",
            "callback_url": settings.PAYMENT_CALLBACK_URL
        }

        try:
            res_data = requests.post(url, json=data, headers=headers, timeout=10).json()
        except (requests.exceptions.RequestException, ValueError):
            logger.exception(f"Payment init failed for package {package_id}")
            return Response({"error": "Payment gateway unavailable"}, status=500)

        if res_data.get("status"):
            # Only save reference if not already set
            if not package.payment_reference:
                package.payment_reference = res_data["data"]["reference"]
                package.save(update_fields=['payment_reference'])

            # ---- Send email BEFORE returning ----
            admin_emails = list(User.objects.filter(is_superuser=True).values_list('email', flat=True))
            recipients = [receiver_email] + admin_emails + [settings.NOTIFY_EMAIL]

            send_email(
                subject="Package Payment Initiated",
                message=f"Payment has been initiated for Package {package.package_id}. Payment URL: {res_data['data']['authorization_url']}",
                recipients=recipients
            )

            return Response({
                "payment_url": res_data["data"]["authorization_url"],
                "qr_code": f"https://api.qrserver.com/v1/create-qr-code/?data={res_data['data']['authorization_url']}&size=200x200"
            })

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

        # Verify webhook signature
        expected_hash = hmac.new(secret.encode(), request.body, hashlib.sha512).hexdigest()
        if not hmac.compare_digest(signature or '', expected_hash):
            logger.warning("Paystack webhook signature mismatch")
            return Response(status=400)

        try:
            payload = json.loads(request.body)
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
            # Use select_for_update to prevent race conditions
            with transaction.atomic():
                package = Package.objects.select_for_update().get(payment_reference=reference)

                if package.is_paid:
                    logger.info(f"Package {package.id} already marked as paid. Ignoring webhook.")
                    return Response(status=200)

                # Mark package as paid
                package.is_paid = True
                package.save(update_fields=['is_paid'])
                logger.info(f"Package {package.id} marked as paid via webhook.")

                # Send emails
                admin_emails = list(User.objects.filter(is_superuser=True).values_list('email', flat=True))
                recipients = [
                    package.customer.email,
                    package.rider.email if package.rider else None
                ] + admin_emails + [settings.NOTIFY_EMAIL]
                recipients = [r for r in recipients if r]  # remove None

                send_email(
                    subject="Payment Successful",
                    message=f"Package {package.package_id} has been paid successfully.",
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
            package = Package.objects.get(id=package_id, rider=request.user)
        except Package.DoesNotExist:
            return Response({"error": "Not your package"}, status=403)

        PackageTracking.objects.create(package=package, rider=request.user, latitude=lat, longitude=lng)

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"tracking_{package.id}",
            {"type": "send_location", "lat": lat, "lng": lng}
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
        if not tracking:
            return Response({"error": "No tracking data"}, status=404)

        return Response({
            "package_id": package.package_id,
            "status": package.status,
            "lat": tracking.latitude,
            "lng": tracking.longitude,
            "delivery_lat": package.delivery_lat,
            "delivery_lng": package.delivery_lng,
        })



class CustomerPackagesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        latest_tracking = PackageTracking.objects.order_by('-timestamp')
        packages = Package.objects.filter(customer=request.user).select_related('rider').prefetch_related(
            Prefetch('rider__riderprofile'),
            Prefetch('packagetracking_set', queryset=latest_tracking, to_attr='latest_tracking')
        )

        data = []
        for p in packages:
            rider_profile = getattr(p.rider, 'riderprofile', None) if p.rider else None
            tracking = p.latest_tracking[0] if getattr(p, 'latest_tracking', []) else None

            data.append({
                "id": p.id,
                "description": p.description,
                "price": float(p.price),
                "is_paid": p.is_paid,
                "status": p.status,
                "delivery_code": p.delivery_code,
                "rider": {
                    "username": p.rider.username if p.rider else None,
                    "phone": rider_profile.phone_number if rider_profile else None,
                    "rating": float(rider_profile.rating) if rider_profile else None,
                    "rating_count": rider_profile.rating_count if rider_profile else 0,
                    "net_earning": float(p.rider_earning - p.commission) if p.rider else 0  # NEW: net earning
                },
                "tracking": {"lat": tracking.latitude if tracking else None, "lng": tracking.longitude if tracking else None},
                "created_at": p.created_at,
            })

        return Response(data)



# ------------------------------
# Rider Wallet & Withdrawal
# ------------------------------
class RiderWalletView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def get(self, request):
        wallet, _ = RiderWallet.objects.get_or_create(rider=request.user)
        return Response({"balance": float(wallet.balance), "total_earned": float(wallet.total_earned)})


class RiderWithdrawView(APIView):
    throttle_classes = [LoginThrottle]
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def post(self, request):
        try:
            amount = Decimal(request.data.get('amount'))
            if amount <= 0:
                raise InvalidOperation()
        except (TypeError, InvalidOperation):
            return Response({"error": "Invalid amount"}, status=400)

        bank_account = request.data.get('bank_account')
        bank_code = request.data.get('bank_code')
        if not bank_account or not bank_code:
            return Response({"error": "Bank account and code are required"}, status=400)

        try:
            with transaction.atomic():
                wallet, _ = RiderWallet.objects.select_for_update().get_or_create(rider=request.user)

                if amount > wallet.balance:
                    return Response({"error": "Insufficient funds"}, status=400)

                headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}
                recipient_data = {
                    "type": "nuban",
                    "name": request.user.username,
                    "account_number": bank_account,
                    "bank_code": bank_code,
                    "currency": "NGN"
                }

                # Create recipient
                try:
                    recipient_res = requests.post(
                        "https://api.paystack.co/transferrecipient",
                        json=recipient_data,
                        headers=headers,
                        timeout=10
                    ).json()
                except (requests.exceptions.RequestException, ValueError):
                    logger.exception("Paystack transfer recipient creation failed")
                    return Response({"error": "Paystack unavailable"}, status=500)

                if not recipient_res.get("status"):
                    return Response({"error": "Recipient creation failed", "details": recipient_res}, status=400)

                transfer_data = {
                    "source": "balance",
                    "amount": int(amount * 100),
                    "recipient": recipient_res["data"]["recipient_code"],
                    "reason": "Rider Payout"
                }

                # Execute transfer
                try:
                    res_data = requests.post(
                        "https://api.paystack.co/transfer",
                        json=transfer_data,
                        headers=headers,
                        timeout=10
                    ).json()
                except (requests.exceptions.RequestException, ValueError):
                    logger.exception("Paystack transfer failed")
                    return Response({"error": "Paystack unavailable"}, status=500)

                if res_data.get("status"):
                    # Deduct from wallet only if transfer succeeds
                    wallet.withdraw(amount)

                    # Send email to rider, admins, and notify email
                    admin_emails = list(User.objects.filter(is_superuser=True).values_list('email', flat=True))
                    recipients = [request.user.email] + admin_emails + [settings.NOTIFY_EMAIL]
                    recipients = [r for r in recipients if r]

                    send_email(
                        subject="Withdrawal Successful",
                        message=f"Rider {request.user.username} has withdrawn ₦{amount}. Current balance: ₦{wallet.balance}.",
                        recipients=recipients
                    )

                    return Response({
                        "message": f"Withdrawal of ₦{amount} successful",
                        "current_balance": float(wallet.balance)
                    })

                logger.warning(f"Paystack transfer failed: {res_data}")
                return Response({"error": "Paystack transfer failed", "details": res_data}, status=400)

        except Exception as e:
            logger.exception("Error during withdrawal")
            return Response({"error": "Withdrawal failed"}, status=500)
        


# ------------------------------
# Rating & Reviews
# ------------------------------
class RateRiderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, package_id):
        try:
            package = Package.objects.get(id=package_id, customer=request.user, status='delivered')
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
    


class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        return Response({
            "username": user.username,   # 🔥 important
            "email": user.email,
            "phone_number": user.phone_number,
            "role": user.role,
            "user_id": user.user_id,
        })
    


class DeleteUserView(APIView):
    permission_classes = [IsAuthenticated]
    def delete(self, request):
        user = request.user
        user.delete()
        return Response({"detail": "Account deleted successfully."}, status=status.HTTP_204_NO_CONTENT)
    

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_profile(request):
    """
    Delete the currently authenticated user's account.
    """
    user = request.user
    user.delete()
    return Response({"detail": "Account deleted successfully."}, status=status.HTTP_204_NO_CONTENT)

        

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