# notifications.py
from senmi.models import Notification
from django.contrib.auth import get_user_model
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


def send_live_notification(user_id, data):
    try:
        user = User.objects.get(id=user_id)

        Notification.objects.create(
            user=user,
            type=data.get("type", ""),
            message=data.get("message", "")
        )

        channel_layer = get_channel_layer()

        print("SENDING TO GROUP:", f"user_{user_id}")

        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}",
            {
                "type": "notify",
                "data": {
                    "message": data.get("message", ""),
                    "type": data.get("type", "")
                }
            }
        )

    except Exception as e:
        logger.exception(f"Notification failed: {e}")