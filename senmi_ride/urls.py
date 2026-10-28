from django.urls import path

from senmi_ride.notifications import AdminRideNotificationView, MarkRideNotificationReadView
from senmi_ride.notifications import MyRideNotificationsView

# ============================================================
# CORE RIDE VIEWS
# ============================================================

from .views import (
    AdminAllRidesView,
    AdminCommissionPaymentsView,
    AdminCustomersView,
    AdminDriverActivityView,
    AdminDriverDetailView,
    AdminDriverStatusView,
    AdminDriversView,
    AdminRideAnalyticsView,
    DriverCommissionHistoryView,
    DriverDeleteRideHistoryView,
    DriverRideHistoryView,
    DriverStatsView,
    RegisterRideFCMTokenView,
    RideDriverProfileView,
    AvailableRidesView,
    AcceptRideView,
    DriverActiveRidesView,
    UpdateRideStatusView,
    RideTrackingView,
    RideRatingView,
    RideDriverWalletView,
    RideCommissionPaymentView,
    VerifyRideCommissionPaymentView,
)


# ============================================================
# CUSTOMER RIDE VIEWS
# ============================================================

from .customer import (
    RideFareQuoteView,
    CreateRideView,
    PassengerRideHistoryView,
    PassengerActiveRidesView,
    PassengerRideDetailView,
    PassengerCancelRideView,
    CreateRideShareView,
    PublicRideTrackingView,
)


# ============================================================
# DRIVER VIEWS
# ============================================================

from .driver import (
    DriverOnlineStatusView,
    DriverAvailabilityLocationView,
    DriverCancelRideView,
)


urlpatterns = [

    # ========================================================
    # DRIVER PROFILE
    # ========================================================

    path(
        "driver/profile/",
        RideDriverProfileView.as_view(),
        name="ride-driver-profile",
    ),

    # ========================================================
    # DRIVER ONLINE / OFFLINE
    # ========================================================

    path(
        "driver/online/",
        DriverOnlineStatusView.as_view(),
        name="ride-driver-online",
    ),

    # ========================================================
    # DRIVER GPS AVAILABILITY
    # ========================================================

    path(
        "driver/location/",
        DriverAvailabilityLocationView.as_view(),
        name="ride-driver-location",
    ),

    path(
        "rides/<str:ride_id>/share/",
        CreateRideShareView.as_view(),
        name="create-ride-share",
    ),

    
    
    path(
        "rides/shared/<str:token>/",
        PublicRideTrackingView.as_view(),
        name="public-ride-tracking",
        ),
    # ========================================================
    # PASSENGER
    # ========================================================

    path(
        "rides/quote/",
        RideFareQuoteView.as_view(),
        name="ride-fare-quote",
    ),

    path(
        "rides/create/",
        CreateRideView.as_view(),
        name="create-ride",
    ),

    # ================================
    # PASSENGER RIDE HISTORY
    # ================================

    path(
        "rides/passenger/history/",
        PassengerRideHistoryView.as_view(),
        name="passenger-ride-history",
    ),

    path(
        "rides/passenger/active/",
        PassengerActiveRidesView.as_view(),
        name="passenger-active-rides",
    ),


    path(
    "rides/available/",
    AvailableRidesView.as_view(),
    name="available-rides",
    ),

    path(
        "rides/<str:ride_id>/",
        PassengerRideDetailView.as_view(),
        name="passenger-ride-detail",
    ),

    path(
        "rides/<str:ride_id>/cancel/",
        PassengerCancelRideView.as_view(),
        name="passenger-ride-cancel",
    ),


    # ========================================================
    # DRIVER
    # ========================================================

    path(
        "rides/<str:ride_id>/accept/",
        AcceptRideView.as_view(),
        name="accept-ride",
    ),

    path(
        "rides/driver/active/",
        DriverActiveRidesView.as_view(),
        name="driver-active-rides",
    ),

    path(
        "rides/<str:ride_id>/driver-cancel/",
        DriverCancelRideView.as_view(),
        name="driver-cancel-ride",
    ),

    # ========================================================
    # RIDE STATUS
    # ========================================================

    path(
        "rides/<str:ride_id>/status/",
        UpdateRideStatusView.as_view(),
        name="update-ride-status",
    ),

    # ========================================================
    # TRACKING
    # ========================================================

    path(
        "rides/<str:ride_id>/tracking/",
        RideTrackingView.as_view(),
        name="ride-tracking",
    ),

    # ========================================================
    # RATING
    # ========================================================

    path(
        "rides/<str:ride_id>/rating/",
        RideRatingView.as_view(),
        name="ride-rating",
    ),

    # ========================================================
    # WALLET
    # ========================================================

    path(
        "driver/wallet/",
        RideDriverWalletView.as_view(),
        name="ride-driver-wallet",
    ),

    # ========================================================
    # DRIVER → SENMI COMMISSION
    # ========================================================

    path(
        "commission/pay/",
        RideCommissionPaymentView.as_view(),
        name="ride-commission-pay",
    ),

    path(
        "commission/verify/<str:reference>/",
        VerifyRideCommissionPaymentView.as_view(),
        name="verify-ride-commission",
    ),

        # ========================================================
    # DRIVER HISTORY
    # ========================================================

    path(
        "rides/driver/history/",
        DriverRideHistoryView.as_view(),
        name="driver-ride-history",
    ),

    path(
        "rides/<str:ride_id>/driver-delete/",
        DriverDeleteRideHistoryView.as_view(),
        name="driver-delete-ride-history",
    ),

    # ========================================================
    # DRIVER STATS
    # ========================================================

    path(
        "driver/stats/",
        DriverStatsView.as_view(),
        name="driver-stats",
    ),

    # ========================================================
    # DRIVER COMMISSION HISTORY
    # ========================================================

    path(
        "commission/history/",
        DriverCommissionHistoryView.as_view(),
        name="driver-commission-history",
    ),
    path(
        "admin/rides/",
        AdminAllRidesView.as_view(),
        name="admin-all-rides",
    ),

    path(
    "admin/drivers/",
    AdminDriversView.as_view(),
    name="admin-drivers",
    ),
    path(
    "admin/drivers/<str:driver_id>/",
    AdminDriverDetailView.as_view(),
    name="admin-driver-detail",
    ),
    path(
    "admin/customers/",
    AdminCustomersView.as_view(),
    name="admin-customers",
    ),
    path(
    "admin/drivers/<str:driver_id>/activity/",
    AdminDriverActivityView.as_view(),
    name="admin-driver-activity",
    ),
    path(
    "admin/commission-payments/",
    AdminCommissionPaymentsView.as_view(),
    name="admin-commission-payments",
    ),
    path(
    "admin/analytics/",
    AdminRideAnalyticsView.as_view(),
    name="admin-ride-analytics",
    ),

    # Ride notifications
    path(
        "admin/notifications/",
        AdminRideNotificationView.as_view(),
        name="ride-admin-notifications",
    ),
    path(
        "notifications/",
        MyRideNotificationsView.as_view(),
        name="ride-my-notifications",
    ),
    path(
        "notifications/<int:recipient_id>/read/",
        MarkRideNotificationReadView.as_view(),
        name="ride-notification-read",
    ),

    path(
    "device/register/",
    RegisterRideFCMTokenView.as_view(),
    name="ride-fcm-token-register",
    ),

    path(
    "admin/drivers/<str:driver_id>/status/",
    AdminDriverStatusView.as_view(),
    name="admin-driver-status",
    ),
]