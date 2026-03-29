import random
from django.db import models
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated, IsAdminUser
from rest_framework.decorators import api_view, permission_classes
from django.core.mail import send_mail
from django.conf import settings
import uuid
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import requests
from senmi.models import User
from rest_framework_simplejwt.tokens import RefreshToken
from django.db.models import Q, Avg, Count
from .serializers import RegisterSerializer, RiderProfileSerializer, CustomLoginSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from .models import RiderProfile

class CustomLoginView(TokenObtainPairView):
    serializer_class = CustomLoginSerializer




class AdminRidersListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        riders = RiderProfile.objects.select_related('user').all()

        data = []
        for r in riders:
            data.append({
                "id": r.id,
                "username": r.user.username,
                "email": r.user.email,
                "status": r.status,
                "phone": r.phone_number,
                "city": r.city,

                # ✅ ADD IMAGES
                "profile_picture": r.profile_picture.url if r.profile_picture else None,
                "rider_image_1": r.rider_image_1.url if r.rider_image_1 else None,
                "rider_image_with_vehicle": r.rider_image_with_vehicle.url if r.rider_image_with_vehicle else None,
            })

        return Response(data)
    


    
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

            # ✅ Generate JWT token for auto-login
            refresh = RefreshToken.for_user(user)
            access_token = str(refresh.access_token)

            return Response({
                "message": "User created successfully",
                "role": user.role,
                "username": user.username,
                "access": access_token  # <-- Flutter will use this
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)




class RiderLoginAPIView(APIView):
    def post(self, request):
        email = request.data.get("email")
        password = request.data.get("password")
        user = authenticate(username=email, password=password)

        if user:
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
                "is_admin": user.is_superuser  # ✅ ADD THIS
            })

        return Response({"detail": "Invalid credentials"}, status=401)




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
            required_images = ['profile_picture', 'rider_image_1', 'rider_image_with_vehicle']
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
    



from .models import Package, PackageStatusHistory, PackageTracking, RiderRating, RiderWallet
from django.http import JsonResponse

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
            pickup_lat__isnull=False
        )

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

        if package.payment_type == "sender" and not package.is_paid:
            return Response({"error": "Sender has not paid"}, status=400)

        # ✅ Prevent multiple riders
        if package.rider is not None:
            return Response({"error": "Already taken"}, status=400)

        # Assign rider
        package.rider = request.user
        package.status = 'accepted'
        package.save()

        PackageStatusHistory.objects.create(
            package=package,
            status='accepted'
        )

        return Response({"message": "Accepted successfully"})
    



from rest_framework.permissions import IsAuthenticated
from .serializers import PackageSerializer

class CreatePackageView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != 'customer':
            return Response({"error": "Only customers can create packages"}, status=403)

        serializer = PackageSerializer(data=request.data)
        if serializer.is_valid():
            package = serializer.save(customer=request.user)

            # If receiver pays, generate delivery code and payment link
            if package.payment_type == "receiver":
                package.delivery_code = f"{random.randint(1000, 9999)}"
                package.save()

            return Response({
                **serializer.data,
                "package_id": package.package_id,
                "delivery_code": package.delivery_code
            }, status=201)
        
        return Response(serializer.errors, status=400)
    



class UpdateDeliveryStatusView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def post(self, request, package_id):
        try:
            package = Package.objects.get(id=package_id)
        except Package.DoesNotExist:
            return Response({"error": "Package not found"}, status=404)

        if package.rider != request.user:
            return Response({"error": "Not your package"}, status=403)

        new_status = request.data.get('status')
        valid_flow = {
            'accepted': 'picked_up',
            'picked_up': 'delivered'
        }

        if package.status not in valid_flow:
            return Response({"error": "Invalid current status"}, status=400)

        if new_status != valid_flow[package.status]:
            return Response({"error": "Invalid status transition"}, status=400)

        # Require delivery code if marking as delivered
        if new_status == "delivered":
            code_input = request.data.get('delivery_code')
            if not code_input:
                return Response({"error": "Delivery code required"}, status=400)
            if package.delivery_code != code_input:
                return Response({"error": "Invalid delivery code"}, status=400)

            wallet, _ = RiderWallet.objects.get_or_create(rider=request.user)
            wallet.deposit(package.rider_earning)

            if package.payment_type == "receiver":
                wallet.balance -= package.commission
                package.is_collected = True

            wallet.save()
            package.save()

        package.status = new_status
        package.save()
        PackageStatusHistory.objects.create(package=package, status=new_status)

        return Response({"message": f"Package marked as {new_status}"})

    



class RiderEarningsView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def get(self, request):
        deliveries = Package.objects.filter(rider=request.user, status='delivered')

        total_earnings = sum([p.rider_earning for p in deliveries])

        return Response({
            "total_earnings": float(total_earnings),
            "total_deliveries": deliveries.count()
        })
    


import requests
from django.conf import settings
class InitializeReceiverPaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, package_id):
        from django.conf import settings

        try:
            package = Package.objects.get(id=package_id)
        except Package.DoesNotExist:
            return Response({"error": "Package not found"}, status=404)

        if package.payment_type != "receiver":
            return Response({"error": "This package is not set for receiver payment"}, status=400)

        if package.is_paid:
            return Response({"error": "Package already paid"}, status=400)

        receiver_email = request.data.get("receiver_email") or package.receiver_email
        if not receiver_email:
            return Response({"error": "Receiver email is required"}, status=400)

        # Paystack init
        url = "https://api.paystack.co/transaction/initialize"
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "email": receiver_email,
            "amount": int(package.price * 100),
            "reference": f"PKG-{package.id}-{uuid.uuid4().hex[:6]}",
            "callback_url": f"https://yourdomain.com/payment-success/{package.id}/"
        }

        response = requests.post(url, json=data, headers=headers)
        res_data = response.json()

        if res_data.get("status"):
            package.payment_reference = res_data["data"]["reference"]
            package.save()

            # Return payment URL & optional QR
            return Response({
                "payment_url": res_data["data"]["authorization_url"],
                "qr_code": f"https://api.qrserver.com/v1/create-qr-code/?data={res_data['data']['authorization_url']}&size=200x200"
            })

        return Response({"error": "Payment initialization failed"}, status=400)
    



from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import hashlib
import hmac

@method_decorator(csrf_exempt, name='dispatch')
class PaystackWebhookView(APIView):

    def post(self, request):
        secret = settings.PAYSTACK_SECRET_KEY

        hash = hmac.new(
            secret.encode('utf-8'),
            request.body,
            hashlib.sha512
        ).hexdigest()

        if hash != request.headers.get('x-paystack-signature'):
            return Response(status=400)

        payload = request.data
        event = payload.get('event')

        if event == 'charge.success':
            data = payload.get('data')
            reference = data.get('reference')

            try:
                package = Package.objects.get(payment_reference=reference)
                package.is_paid = True
                package.save()
            except Package.DoesNotExist:
                pass

        return Response(status=200)
    



class UpdateLocationView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def post(self, request, package_id):
        lat = request.data.get('lat')
        lng = request.data.get('lng')

        try:
            package = Package.objects.get(id=package_id, rider=request.user)
        except Package.DoesNotExist:
            return Response({"error": "Not your package"}, status=403)

        # ✅ Save to DB (you already have this)
        PackageTracking.objects.create(
            package=package,
            rider=request.user,
            latitude=lat,
            longitude=lng
        )

        # 🚀 SEND REALTIME UPDATE (THIS IS THE NEW PART)
        channel_layer = get_channel_layer()

        async_to_sync(channel_layer.group_send)(
            f"tracking_{package.id}",  # room name
            {
                "type": "send_location",
                "lat": lat,
                "lng": lng,
            }
        )

        return Response({"message": "Location updated"})
    


class TrackPackageView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, package_id):  # keep name same

        try:
            # 🔥 CHANGE THIS LINE
            package = Package.objects.get(package_id=package_id)
        except Package.DoesNotExist:
            return Response({"error": "Package not found"}, status=404)

        tracking = PackageTracking.objects.filter(
            package=package
        ).order_by('-timestamp')[:1]

        if not tracking:
            return Response({"error": "No tracking data"})

        t = tracking[0]
    
        return Response({
            "package_id": package.package_id,
            "status": package.status,
            "lat": t.latitude,
            "lng": t.longitude,
            "delivery_lat": package.delivery_lat,
            "delivery_lng": package.delivery_lng,
        })
            



class CustomerPackagesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        packages = Package.objects.filter(customer=request.user)
        data = []

        for p in packages:
            rider_profile = getattr(p.rider, 'riderprofile', None) if p.rider else None
            tracking = PackageTracking.objects.filter(package=p).order_by('-timestamp').first()

            data.append({
                "id": p.id,
                "description": p.description,
                "price": float(p.price),
                "is_paid": p.is_paid,
                "status": p.status,
                "delivery_code": p.delivery_code,  # NEW
                "rider": {
                    "username": p.rider.username if p.rider else None,
                    "phone": rider_profile.phone_number if rider_profile else None,
                    "rating": float(rider_profile.rating) if rider_profile else None,
                    "rating_count": rider_profile.rating_count if rider_profile else 0
                },
                "tracking": {
                    "lat": tracking.latitude if tracking else None,
                    "lng": tracking.longitude if tracking else None,
                },
                "created_at": p.created_at,
            })

        return Response(data)
    



class RiderWalletView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def get(self, request):
        wallet, created = RiderWallet.objects.get_or_create(rider=request.user)
        return Response({
            "balance": float(wallet.balance),
            "total_earned": float(wallet.total_earned)
        })
    




class RiderWithdrawView(APIView):
    permission_classes = [IsAuthenticated, IsApprovedRider]

    def post(self, request):
        wallet, _ = RiderWallet.objects.get_or_create(rider=request.user)
        amount = float(request.data.get('amount', 0))

        # 1️⃣ Check balance
        if amount > wallet.balance:
            return Response({"error": "Insufficient funds"}, status=status.HTTP_400_BAD_REQUEST)

        bank_account = request.data.get('bank_account')
        bank_code = request.data.get('bank_code')

        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }

        # ✅ STEP 1: Create recipient (FIX)
        recipient_data = {
            "type": "nuban",
            "name": request.user.username,
            "account_number": bank_account,
            "bank_code": bank_code,
            "currency": "NGN"
        }

        recipient_res = requests.post(
            "https://api.paystack.co/transferrecipient",
            json=recipient_data,
            headers=headers
        ).json()

        if not recipient_res.get("status"):
            return Response({"error": "Recipient creation failed", "details": recipient_res}, status=400)

        recipient_code = recipient_res["data"]["recipient_code"]

        # ✅ STEP 2: Transfer money (FIX)
        transfer_data = {
            "source": "balance",
            "amount": int(amount * 100),
            "recipient": recipient_code,
            "reason": "Rider Payout"
        }

        response = requests.post(
            "https://api.paystack.co/transfer",
            json=transfer_data,
            headers=headers
        )

        res_data = response.json()

        # 3️⃣ Deduct wallet
        if res_data.get("status"):
            wallet.withdraw(amount)
            return Response({
                "message": f"Withdrawal of ₦{amount} successful",
                "current_balance": float(wallet.balance)
            })

        return Response({"error": "Paystack transfer failed", "details": res_data}, status=400)
    



class RateRiderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, package_id):
        try:
            package = Package.objects.get(
                id=package_id,
                customer=request.user,
                status='delivered'
            )
        except Package.DoesNotExist:
            return Response({"error": "Invalid package"}, status=404)

        if hasattr(package, 'riderrating'):
            return Response({"error": "Already rated"}, status=400)

        try:
            rating = int(request.data.get('rating'))
        except (TypeError, ValueError):
            return Response({"error": "Rating must be a number"}, status=400)

        comment = request.data.get('comment', '')

        if package.status != 'delivered':
            return Response({"error": "Cannot rate before delivery"}, status=400)

        if rating < 1 or rating > 5:
            return Response({"error": "Rating must be 1–5"}, status=400)

        if not package.rider:
            return Response({"error": "No rider assigned"}, status=400)

        # ✅ Save rating
        RiderRating.objects.create(
            rider=package.rider,
            customer=request.user,
            package=package,
            rating=rating,
            comment=comment
        )

        #SUPER OPTIMIZED (DB handles everything)
        rider_profile = getattr(package.rider, 'riderprofile', None)
        if rider_profile:
            stats = package.rider.ratings.aggregate(
                avg=Avg('rating'),
                count=Count('id')
            )

            rider_profile.rating = round(stats['avg'] or 0, 1)
            rider_profile.rating_count = stats['count'] or 0
            rider_profile.save(update_fields=['rating', 'rating_count'])

        return Response({"message": "Rating submitted"})



class PackageTimelineView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, package_id):
        history = PackageStatusHistory.objects.filter(package_id=package_id).order_by('timestamp')

        data = []
        for h in history:
            data.append({
                "status": h.status,
                "time": h.timestamp
            })

        return Response(data)
    


class AdminUserSearchView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        query = request.GET.get('q')

        # ✅ check inside the function
        if not query:
            return Response({"error": "Enter search query"}, status=400)

        users = User.objects.filter(
            Q(email__icontains=query) |
            Q(username__icontains=query) |
            Q(user_id__icontains=query)
        )

        data = []
        for u in users:
            data.append({
                "user_id": u.user_id,
                "email": u.email,
                "role": u.role,
                "is_active": u.is_active
            })

        return Response(data)
    


class RiderStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'rider':
            return Response({"role": request.user.role})

        profile = getattr(request.user, 'riderprofile', None)

        if not profile:
            return Response({"status": "pending", "rejection_reason": None})

        return Response({
            "status": profile.status,
            "rejection_reason": profile.rejection_reason
        })