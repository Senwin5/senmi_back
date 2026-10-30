
import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    RideNotification,
    RideNotificationRecipient,
    RideFCMDevice,
)
from .permissions import IsRideAdmin
from .fcm import send_ride_fcm_notification



logger = logging.getLogger(__name__)


def send_driver_commission_reminder(driver, balance):
    """
    Create an in-app commission reminder and send an FCM
    push notification after the database transaction commits.
    """

    title = "Outstanding Commission Reminder"

    message = (
        f"Your outstanding Senmi commission is "
        f"₦{balance:,.2f}. Please settle your commission."
    )

    try:
        notification = RideNotification.objects.create(
            sender=None,
            target="single",
            title=title,
            message=message,
        )

        recipient_record = RideNotificationRecipient.objects.create(
            notification=notification,
            recipient=driver,
        )

        notification_id = notification.id

        def send_push():
            try:
                send_ride_fcm_notification(
                    user=driver,
                    title=title,
                    body=message,
                    data={
                        "type": "ride_commission_reminder",
                        "ride_notification_id": str(notification_id),
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to send commission reminder to driver %s.",
                    driver.id,
                )

        transaction.on_commit(send_push)

    except Exception:
        logger.exception(
            "Failed to create commission reminder for driver %s.",
            driver.id,
        )

    transaction.on_commit(send_push)


User = get_user_model()
logger = logging.getLogger(__name__)


def notification_data(notification, recipient_record=None):
    data = {
        "id": notification.id,
        "title": notification.title,
        "message": notification.message,
        "target": notification.target,
        "created_at": notification.created_at,
    }

    if recipient_record is not None:
        data.update({
            "recipient_id": recipient_record.id,
            "is_read": recipient_record.is_read,
            "read_at": recipient_record.read_at,
        })

    return data


class AdminRideNotificationView(APIView):
    permission_classes = [IsAuthenticated, IsRideAdmin]

    def get(self, request):
        notifications = (
            RideNotification.objects
            .filter(sender__isnull=False)
            .annotate(
                recipient_count=Count("recipients", distinct=True)
            )
            .order_by("-created_at")
        )

        data = [
            {
                **notification_data(notification),
                "recipient_count": notification.recipient_count,
                "sender_id": notification.sender_id,
            }
            for notification in notifications
        ]

        return Response(data)

    @transaction.atomic
    def post(self, request):
        title = str(request.data.get("title", "")).strip()
        message = str(request.data.get("message", "")).strip()
        target = str(request.data.get("target", "")).strip().lower()
        user_id = request.data.get("user_id")

        if not title or not message:
            return Response(
                {"error": "Title and message are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(title) > 200:
            return Response(
                {"error": "Title cannot exceed 200 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if target not in {"all", "drivers", "passengers", "single"}:
            return Response(
                {
                    "error": (
                        "Target must be all, drivers, "
                        "passengers, or single."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Determine the Ride notification recipients.
        if target == "single":
            if not user_id:
                return Response(
                    {
                        "error": (
                            "user_id is required for a single user."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            selected_user = get_object_or_404(User, pk=user_id)
            users = User.objects.filter(pk=selected_user.pk)

        elif target == "drivers":
            users = User.objects.filter(
                ride_driver_profile__isnull=False
            )

        elif target == "passengers":
            users = (
                User.objects
                .filter(ride_requests__isnull=False)
                .exclude(ride_driver_profile__isnull=False)
                .distinct()
            )

        else:
            # Include non-staff users and the sending admin.
            users = User.objects.filter(
                Q(is_staff=False, is_superuser=False)
                | Q(pk=request.user.pk)
            )

        users = users.distinct()

        if not users.exists():
            return Response(
                {"error": "No users were found for this audience."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Save the Ride notification.
        notification = RideNotification.objects.create(
            sender=request.user,
            target=target,
            title=title,
            message=message,
        )

        # Save each recipient's Ride inbox entry.
        recipient_records = [
            RideNotificationRecipient(
                notification=notification,
                recipient=user,
            )
            for user in users.iterator()
        ]

        RideNotificationRecipient.objects.bulk_create(
            recipient_records,
            batch_size=1000,
        )

        # Schedule Ride-specific push notifications after commit.
        notification_id = notification.id

        for record in recipient_records:
            recipient_user_id = record.recipient_id

            def send_after_commit(
                user_id=recipient_user_id,
                ride_notification_id=notification_id,
                notification_target=target,
                notification_title=title,
                notification_message=message,
            ):
                try:
                    recipient = User.objects.filter(
                        pk=user_id
                    ).first()

                    if recipient is None:
                        logger.warning(
                            "Ride notification recipient %s not found.",
                            user_id,
                        )
                        return

                    send_ride_fcm_notification(
                        user=recipient,
                        title=notification_title,
                        body=notification_message,
                        data={
                            "type": "ride_admin_notification",
                            "ride_notification_id": str(
                                ride_notification_id
                            ),
                            "target": notification_target,
                        },
                    )

                except Exception:
                    logger.exception(
                        "Failed to send Ride notification to user %s.",
                        user_id,
                    )

            transaction.on_commit(send_after_commit)

        return Response(
            {
                "success": True,
                "message": "Ride notification created successfully.",
                "notification": notification_data(notification),
                "recipient_count": len(recipient_records),
            },
            status=status.HTTP_201_CREATED,
        )


class RideFCMTokenRegisterView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = str(request.data.get("token", "")).strip()

        if not token:
            return Response(
                {"error": "FCM token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        RideFCMDevice.objects.update_or_create(
            token=token,
            defaults={
                "user": request.user,
                "is_active": True,
            },
        )

        return Response(
            {
                "success": True,
                "message": "Ride device token registered successfully.",
            },
            status=status.HTTP_200_OK,
        )


class MyRideNotificationsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        records = (
            RideNotificationRecipient.objects
            .filter(recipient=request.user)
            .select_related("notification")
            .order_by("-notification__created_at")
        )

        data = [
            notification_data(record.notification, record)
            for record in records
        ]

        return Response(data)


class MarkRideNotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, recipient_id):
        record = get_object_or_404(
            RideNotificationRecipient,
            pk=recipient_id,
            recipient=request.user,
        )

        if not record.is_read:
            record.is_read = True
            record.read_at = timezone.now()
            record.save(update_fields=["is_read", "read_at"])

        return Response(
            {
                "success": True,
                "message": "Notification marked as read.",
                "recipient_id": record.id,
                "is_read": record.is_read,
            },
            status=status.HTTP_200_OK,
        )
