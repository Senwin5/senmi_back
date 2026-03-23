from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated, IsAdminUser
from rest_framework.decorators import api_view, permission_classes
from django.core.mail import send_mail
from django.conf import settings
import uuid
import requests
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
    



from .models import Package, PackageTracking, RiderWallet
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
            pickup_lat__isnull=False,
            is_paid=True   # ✅ ONLY PAID PACKAGES
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
    



from rest_framework.permissions import IsAuthenticated
from .serializers import PackageSerializer

class CreatePackageView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != 'customer':
            return Response({"error": "Only customers can create packages"}, status=403)

        serializer = PackageSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save(customer=request.user)
            return Response(serializer.data, status=201)

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

        if new_status == "delivered":
            # Deposit rider earning
            wallet, created = RiderWallet.objects.get_or_create(rider=request.user)
            wallet.deposit(package.rider_earning)

        package.status = new_status
        package.save()

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

class InitializePaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, package_id):
        try:
            package = Package.objects.get(id=package_id, customer=request.user)
        except Package.DoesNotExist:
            return Response({"error": "Package not found"}, status=404)

        url = "https://api.paystack.co/transaction/initialize"

        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }

        data = {
            "email": request.user.email,
            "amount": int(package.price * 100),  # Paystack uses kobo
            "reference": f"PKG-{package.id}-{uuid.uuid4().hex[:6]}",
            "callback_url": "https://yourdomain.com/payment-success/"
        }

        response = requests.post(url, json=data, headers=headers)
        res_data = response.json()

        if res_data.get("status"):
            payment_url = res_data["data"]["authorization_url"]
            reference = res_data["data"]["reference"]

            package.payment_reference = reference
            package.save()

            return Response({
                "payment_url": payment_url
            })

        return Response({"error": "Payment initialization failed"}, status=400)
    


from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

@method_decorator(csrf_exempt, name='dispatch')
class PaystackWebhookView(APIView):

    def post(self, request):
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

        PackageTracking.objects.create(
            package=package,
            rider=request.user,
            latitude=lat,
            longitude=lng
        )

        return Response({"message": "Location updated"})
    


class TrackPackageView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, package_id):
        tracking = PackageTracking.objects.filter(
            package_id=package_id
        ).order_by('-timestamp')[:1]

        if not tracking:
            return Response({"error": "No tracking data"})

        t = tracking[0]

        return Response({
            "lat": t.latitude,
            "lng": t.longitude
        })
    



class CustomerPackagesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        packages = Package.objects.filter(customer=request.user)
        data = []
        for p in packages:
            data.append({
                "id": p.id,
                "description": p.description,
                "price": float(p.price),
                "is_paid": p.is_paid,
                "status": p.status,
                "rider": p.rider.username if p.rider else None
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

        # 1️⃣ Check if the rider has enough balance
        if amount > wallet.balance:
            return Response({"error": "Insufficient funds"}, status=status.HTTP_400_BAD_REQUEST)

        bank_account = request.data.get('bank_account')  # Account number
        bank_code = request.data.get('bank_code')        # Paystack bank code

        # 2️⃣ Call Paystack Payout API
        url = "https://api.paystack.co/transfer"
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }

        data = {
            "source": "balance",
            "amount": int(amount * 100),  # Paystack expects kobo
            "recipient": bank_account,
            "reason": "Rider Payout"
        }

        response = requests.post(url, json=data, headers=headers)
        res_data = response.json()

        # 3️⃣ If successful, deduct from wallet
        if res_data.get("status"):
            wallet.withdraw(amount)
            return Response({
                "message": f"Withdrawal of ₦{amount} successful",
                "current_balance": float(wallet.balance)
            })

        return Response({"error": "Paystack transfer failed", "details": res_data}, status=400)