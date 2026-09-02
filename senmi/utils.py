# senmi/utils.py

from math import atan2, cos, radians, sin, sqrt

from django.contrib.auth import get_user_model
import os
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
import logging
from firebase_admin import messaging
import resend

from senmi_back import settings
from .models import FCMDevice, Notification
from venv import logger


logger = logging.getLogger(__name__)

resend.api_key = os.getenv("RESEND_API_KEY")


def send_email(subject, message, from_email=None, recipient_list=None, recipients=None, fail_silently=False):
    try:
        to = recipient_list or recipients

        html = f"""
        <div style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 30px;">
            <div style="max-width: 600px; margin: auto; background: white; border-radius: 16px; padding: 40px; text-align: center;">
                <img src="https://www.senmi.com.ng/static/logo.png" width="120" style="margin-bottom: 20px;" />

                <h2 style="color:#111;">{subject}</h2>

                <p style="color:#444; line-height:1.7; font-size:15px; white-space: pre-line;">
                    {message}
                </p>

                <div style="margin-top:30px; font-size:13px; color:#888;">
                    © Senmi Real Time Delivery App Ltd.
                </div>
            </div>
        </div>
        """

        return resend.Emails.send({
            "from": "Senmi <support@senmi.com.ng>",
            "to": to,
            "subject": subject,
            "html": html
        })

    except Exception as e:
        logger.error(f"EMAIL FAILED: {str(e)}")
        return False




def send_fcm_notification(
    user=None,
    title="",
    body="",
    data=None,
):
    """
    Send an FCM push notification to ONE supplied user.

    Recipient selection is handled by the caller.
    """

    if not user:
        logger.warning(
            "send_fcm_notification called without user"
        )
        return False

    # =========================================================
    # GET USER'S ACTIVE FCM TOKENS
    # =========================================================

    tokens = list(
        FCMDevice.objects.filter(
            user=user,
            is_active=True,
        ).values_list(
            "token",
            flat=True,
        )
    )

    if not tokens:
        logger.warning(
            f"No active FCM tokens found for user {user.id}"
        )
        return False

    # =========================================================
    # SEND PUSH
    # =========================================================

    success = False

    for token in tokens:
        try:
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body,
                    image="https://www.senmi.com.ng/static/logo.png",
                ),

                android=messaging.AndroidConfig(
                    notification=messaging.AndroidNotification(
                        image="https://www.senmi.com.ng/static/logo.png",
                        icon="notification_icon",
                        color="#ffffff",
                    )
                ),

                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(
                            sound="default",
                            badge=1,
                            content_available=True,
                        )
                    )
                ),

                data={
                    k: str(v)
                    for k, v in (data or {}).items()
                },

                token=token,
            )

            messaging.send(message)

            success = True

        except Exception as e:
            logger.exception(
                f"FCM send failed for user {user.id}: {e}"
            )

    return success




#notify_admin_dashboard flutter admin
def notify_admin_dashboard():
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
        logger.exception(f"Dashboard notification failed: {e}")

   

def notify_admin_withdrawal_request(withdrawal):
    """
    Notify all active admins AND support users that a rider
    has requested a withdrawal.

    Sends:
    1. In-app notification
    2. FCM push notification
    3. Admin dashboard refresh
    """

    User = get_user_model()

    try:
        rider_profile = getattr(
            withdrawal.rider,
            "riderprofile",
            None,
        )

        rider_name = (
            getattr(
                rider_profile,
                "full_name",
                None,
            )
            or withdrawal.rider.email
        )

        message = (
            f"{rider_name} requested a withdrawal of "
            f"₦{withdrawal.amount:,.2f}. "
            f"Withdrawal #{withdrawal.id} is awaiting approval."
        )

        # ==========================================
        # ADMIN + SUPPORT USERS
        # ==========================================

        users = User.objects.filter(
            role__in=["admin", "support"],
            is_active=True,
        )

        for user in users:

            # ==========================================
            # DATABASE / IN-APP NOTIFICATION
            # ==========================================

            Notification.objects.create(
                user=user,
                type="withdrawal_pending",
                message=message,
                target="single",
            )

            # ==========================================
            # FCM PUSH NOTIFICATION
            # ==========================================

            send_fcm_notification(
                user,
                "New Withdrawal Request",
                message,
                {
                    "type": "withdrawal_pending",
                    "withdrawal_id": withdrawal.id,
                },
            )

        # ==========================================
        # REFRESH ADMIN DASHBOARD
        # ==========================================

        notify_admin_dashboard()

        return True

    except Exception as e:
        logger.exception(
            f"Admin/support withdrawal notification failed: {e}"
        )

        return False

    

def email_admin_payment_received(package, payment_data=None):
    """
    Notify all active admin/support users when a package payment
    has been successfully confirmed.
    """
    User = get_user_model()

    try:
        users = (
            User.objects
            .filter(
                role__in=["admin", "support"],
                is_active=True,
            )
            .exclude(email__isnull=True)
            .exclude(email="")
        )

        recipients = list(
            users.values_list("email", flat=True)
        )

        # Main Senmi support email
        recipients.append("senmisupport@gmail.com")

        # Remove duplicates
        recipients = list(set(recipients))

        if not recipients:
            logger.warning(
                "No admin/support payment email recipients found."
            )
            return False

        payment_data = payment_data or {}

        reference = (
            payment_data.get("reference")
            or package.payment_reference
            or "N/A"
        )

        paid_amount = payment_data.get("amount")

        if paid_amount is not None:
            amount_display = f"₦{int(paid_amount) / 100:,.2f}"
        else:
            amount_display = f"₦{package.price:,.2f}"

        completed_at = package.payment_completed_at

        completed_display = (
            completed_at.strftime("%d %B %Y, %I:%M %p")
            if completed_at
            else "N/A"
        )

        subject = (
            f"Customer Payment Received - "
            f"Package {package.package_id}"
        )

        message = f"""
            A customer has successfully paid for a package.

            Package ID:
            {package.package_id}

            Customer:
            {package.customer.username}

            Customer Email:
            {package.customer.email}

            Amount Paid:
            {amount_display}

            Payment Reference:
            {reference}

            Payment Status:
            PAID

            Pickup:
            {package.pickup_address}

            Delivery:
            {package.delivery_address}

            Delivery Code:
            {package.delivery_code}

            Payment Completed:
            {completed_display}

            Please record this payment in the Senmi system.

            Senmi System
            """

        return send_email(
            subject=subject,
            message=message,
            recipients=recipients,
        )

    except Exception as e:
        logger.exception(
            f"Admin/support payment email failed: {e}"
        )
        return False

    

def email_admin_withdrawal_request(withdrawal):
    """
    Email all active admins AND support users
    when a rider requests a withdrawal.
    """

    User = get_user_model()

    try:

        # ==========================================
        # ADMIN + SUPPORT EMAILS
        # ==========================================

        users = (
            User.objects
            .filter(
                role__in=["admin", "support"],
                is_active=True,
            )
            .exclude(
                email__isnull=True
            )
            .exclude(
                email=""
            )
        )

        recipients = list(
            users.values_list(
                "email",
                flat=True,
            )
        )

        # ==========================================
        # ALSO SEND TO MAIN SENMI EMAIL
        # ==========================================

        recipients.append("senmisupport@gmail.com")

        # Remove duplicates
        recipients = list(set(recipients))

        if not recipients:
            logger.warning(
                "No withdrawal notification email recipients found."
            )
            return False

        # ==========================================
        # RIDER INFORMATION
        # ==========================================

        rider_profile = getattr(
            withdrawal.rider,
            "riderprofile",
            None,
        )

        rider_name = (
            getattr(
                rider_profile,
                "full_name",
                None,
            )
            or withdrawal.rider.email
        )

        rider_id = (
            getattr(
                rider_profile,
                "rider_id",
                None,
            )
            or "N/A"
        )

        # ==========================================
        # EMAIL
        # ==========================================

        subject = (
            f"New Withdrawal Request "
            f"#{withdrawal.id} - Senmi"
        )

        message = f"""
            A new rider withdrawal request has been submitted.

            Withdrawal ID:
            #{withdrawal.id}

            Rider:
            {rider_name}

            Rider ID:
            {rider_id}

            Email:
            {withdrawal.rider.email}

            Amount:
            ₦{withdrawal.amount:,.2f}

            Bank:
            {withdrawal.bank_name or "N/A"}

            Bank Account:
            {withdrawal.bank_account}

            Bank Code:
            {withdrawal.bank_code}

            Account Name:
            {withdrawal.account_name or "N/A"}

            Reference:
            {withdrawal.reference or "N/A"}

            Status:
            {withdrawal.status.upper()}

            Created:
            {withdrawal.created_at.strftime("%d %B %Y, %I:%M %p")}

            This withdrawal is awaiting admin approval.

            Please log in to the Senmi admin dashboard to review this request.
            """

        return send_email(
            subject=subject,
            message=message,
            recipients=recipients,
        )

    except Exception as e:

        logger.exception(
            f"Admin/support withdrawal email failed: {e}"
        )

        return False
    


    
from decimal import Decimal, ROUND_HALF_UP
from math import atan2, cos, radians, sin, sqrt

from django.conf import settings
from django.utils import timezone

from .models import PricingConfig


def calculate_distance(lat1, lng1, lat2, lng2):
    R = 6371.0

    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlng / 2) ** 2
    )

    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c


def get_active_pricing():
    return (
        PricingConfig.objects
        .filter(is_active=True)
        .first()
    )


def get_time_multiplier(config):
    hour = timezone.localtime().hour

    if 6 <= hour < 11:
        return config.morning_multiplier

    if 11 <= hour < 15:
        return config.afternoon_multiplier

    if 15 <= hour < 22:
        return config.evening_multiplier

    return config.night_multiplier


def calculate_price(distance_km):
    distance_km = Decimal(str(distance_km))

    if distance_km < 0:
        raise ValueError("Distance cannot be negative.")

    config = get_active_pricing()

    if config:
        base_fee = config.base_fee
        per_km_rate = config.per_km_rate
        fuel_multiplier = config.fuel_multiplier
        time_multiplier = get_time_multiplier(config)

    else:
        base_fee = Decimal(str(settings.BASE_FEE))
        per_km_rate = Decimal(str(settings.PER_KM_RATE))
        fuel_multiplier = Decimal(
            str(settings.FUEL_MULTIPLIER)
        )
        time_multiplier = Decimal("1.00")

    distance_cost = distance_km * per_km_rate

    fare = (
        base_fee + distance_cost
    ) * fuel_multiplier

    fare *= time_multiplier

    # Round to nearest ₦50
    fare = (
        fare / Decimal("50")
    ).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP
    ) * Decimal("50")

    return fare

