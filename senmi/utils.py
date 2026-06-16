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
    target="single"
):
    """
    target:
        - single  → one user
        - all     → all users
        - rider   → all riders
        - customer→ all customers
        - admin   → all admins
    """

    User = get_user_model()

    # ==============================
    # 1. Select recipients
    # ==============================
    if target == "all":
        users = User.objects.all()

    elif target == "rider":
        users = User.objects.filter(role="rider")

    elif target == "customer":
        users = User.objects.filter(role="customer")

    elif target == "admin":
        users = User.objects.filter(role="admin")

    else:
        users = [user] if user else []

    if not users:
        return False

    # ==============================
    # 2. Save notification in DB
    # ==============================
    for u in users:
        try:
            Notification.objects.create(
                user=u,
                type=(data.get("type") if data else "general"),
                message=body
            )
        except Exception as e:
            logger.exception(e)

    # ==============================
    # 3. Get FCM tokens
    # ==============================
    tokens = list(
        FCMDevice.objects.filter(
            user__in=users,
            is_active=True
        ).values_list("token", flat=True)
    )

    if not tokens:
        print("❌ NO TOKENS FOUND")
        return False

    # ==============================
    # 4. Send push
    # ==============================
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
                        icon="notification_icon",  # ✔ Android status icon
                        color="#ffffff"
                    )
                ),

                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(
                            sound="default",
                            badge=1,
                            content_available=True
                        )
                    )
                ),

                data={k: str(v) for k, v in (data or {}).items()},
                token=token,
            )

            messaging.send(message)

        except Exception as e:
            logger.exception(e)

    return True



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

   

from math import atan2, cos, radians, sin, sqrt
from django.utils import timezone
from .models import PricingConfig
def calculate_distance(lat1, lng1, lat2, lng2):
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)

    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def get_active_pricing():
    return PricingConfig.objects.filter(is_active=True).first()


def get_time_multiplier(config):
    hour = timezone.localtime().hour

    if 6 <= hour < 11:
        return config.morning_multiplier
    elif 11 <= hour < 15:
        return config.afternoon_multiplier
    elif 15 <= hour < 22:
        return config.evening_multiplier
    else:
        return config.night_multiplier


def calculate_price(distance_km):
    config = get_active_pricing()

    # fallback if admin config is missing
    base_fee = config.base_fee if config else settings.BASE_FEE
    per_km_rate = config.per_km_rate if config else settings.PER_KM_RATE
    fuel_multiplier = config.fuel_multiplier if config else settings.FUEL_MULTIPLIER

    if not config:
        return (base_fee + (distance_km * per_km_rate)) * fuel_multiplier

    time_multiplier = get_time_multiplier(config)

    return (
        (base_fee + (distance_km * per_km_rate))
        * fuel_multiplier
        * time_multiplier
    )

# Distance & price helpers
"""def calculate_distance(lat1, lng1, lat2, lng2):
    R = 6371.0  # Earth radius in km
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c  # distance in km


def calculate_price(distance_km):
    base_fee = settings.BASE_FEE
    per_km_rate = settings.PER_KM_RATE
    multiplier = settings.FUEL_MULTIPLIER
    return (base_fee + (distance_km * per_km_rate)) * multiplier"""


