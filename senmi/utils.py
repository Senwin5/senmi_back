# senmi/utils.py
from math import radians, sin, cos, sqrt, atan2
from django.conf import settings
import os
import logging
import resend


logger = logging.getLogger(__name__)

def send_email(subject, message, recipients):
    resend.api_key = os.getenv("RESEND_API_KEY")

    try:
        return resend.Emails.send({
            "from": "Senmi <support@senmi.com.ng>",
            "to": recipients,
            "subject": subject,
            "html": f"<p>{message}</p>"
        })

    except Exception as e:
        logger.error(f"EMAIL FAILED: {str(e)}")
        return False
    
    
'''def send_email(subject, message, recipients):
    # Ensure admin always receives a copy
    all_recipients = list(set(recipients + [settings.EMAIL_HOST_USER]))

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=all_recipients,
        fail_silently=False,
    )'''

# ------------------------------
# Distance & price helpers
def calculate_distance(lat1, lng1, lat2, lng2):
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
    return (base_fee + (distance_km * per_km_rate)) * multiplier



from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

def send_live_notification(user_id, payload):
    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        f"user_{user_id}",
        {
            "type": "notify",
            "data": payload
        }
    )