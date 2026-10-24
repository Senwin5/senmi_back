
import logging

from firebase_admin import messaging

from .models import RideFCMDevice

logger = logging.getLogger(__name__)


def send_ride_fcm_notification(user=None, title="", body="", data=None):
    if user is None:
        logger.warning("Ride FCM called without a user")
        return False

    devices = RideFCMDevice.objects.filter(
        user=user,
        is_active=True,
    )

    if not devices.exists():
        logger.warning(
            "No active Ride FCM tokens for user %s",
            user.pk,
        )
        return False

    sent = False

    for device in devices:
        try:
            payload = {
                str(key): str(value)
                for key, value in (data or {}).items()
            }

            payload["title"] = str(title)
            payload["body"] = str(body)

            message = messaging.Message(
                notification=messaging.Notification(
                    title=str(title),
                    body=str(body),
                ),
                data=payload,
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        channel_id="senmi_channel",
                        sound="default",
                    ),
                ),
                token=device.token,
            )

            response = messaging.send(message)

            logger.info(
                "RIDE FCM SENT | user=%s | message=%s",
                user.pk,
                response,
            )
            sent = True

        except messaging.UnregisteredError:
            logger.warning(
                "Deactivating invalid Ride FCM token for user %s",
                user.pk,
            )
            device.is_active = False
            device.save(update_fields=["is_active"])

        except Exception:
            logger.exception(
                "Ride FCM send failed for user %s",
                user.pk,
            )

    return sent
