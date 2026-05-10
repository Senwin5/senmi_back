import os
import resend

resend.api_key = os.getenv("RESEND_API_KEY")


def send_email(to_email, subject, html):
    try:
        resend.Emails.send({
            "from": "Senmi <noreply@senmi.com.ng>",
            "to": [to_email],
            "subject": subject,
            "html": html
        })
        return True
    except Exception as e:
        print("Resend error:", e)
        return False