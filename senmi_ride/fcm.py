import logging

from firebase_admin import messaging

from .models import RideFCMDevice

logger = logging.getLogger(__name__)


def send_ride_fcm_notification(user=None, title="", body="", data=None):
    if user is None:
        logger.warning("Ride FCM called without a user.")
        return False

    devices = RideFCMDevice.objects.filter(
        user=user,
        is_active=True,
    )

    sent = False

    for device in devices:
        try:
            message = messaging.Message(
                notification=messaging.Notification(
                    title=str(title),
                    body=str(body),
                ),
                data={
                    "title": str(title),
                    "body": str(body),
                    **{
                        str(key): str(value)
                        for key, value in (data or {}).items()
                    },
                },
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        sound="default",
                    ),
                ),
                token=device.token,
            )

            messaging.send(message)
            sent = True

        except messaging.UnregisteredError:
            device.is_active = False
            device.save(update_fields=["is_active"])
            logger.warning(
                "Inactive Ride FCM token for user %s",
                user.id,
            )

        except Exception:
            logger.exception(
                "Ride FCM failed for user %s",
                user.id,
            )

    if not sent:
        logger.warning(
            "No Ride push was sent to user %s; "
            "check that an active Ride token is registered.",
            user.id,
        )

    return sent