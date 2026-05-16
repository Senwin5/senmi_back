# senmi/utils.py


from math import radians, sin, cos, sqrt, atan2
from django.conf import settings
import os
import logging
import resend

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





