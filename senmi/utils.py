from django.core.mail import send_mail
from django.conf import settings

def send_email(subject, message, recipients):
    # Ensure admin always receives a copy
    all_recipients = list(set(recipients + [settings.EMAIL_HOST_USER]))

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=all_recipients,
        fail_silently=False,
    )























