# senmi/utils.py
from math import radians, sin, cos, sqrt, atan2
from django.core.mail import send_mail
from django.conf import settings
import random
from django.conf import settings
import os
from math import radians, sin, cos, sqrt, atan2

def send_email(subject, message, recipients):
    import resend  # import INSIDE function (prevents crash at boot)

    resend.api_key = os.getenv("RESEND_API_KEY")

    try:
        return resend.Emails.send({
            "from": "Senmi <support@senmi.com.ng>",
            "to": recipients,
            "subject": subject,
            "html": f"<p>{message}</p>"
        })
    except Exception as e:
        print("Resend error:", e)
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

