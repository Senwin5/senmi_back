from django.urls import path

# ============================================================
# CORE RIDE VIEWS
# ============================================================

from .views import (
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
    CreateRideView,
    PassengerActiveRidesView,
    PassengerRideDetailView,
    PassengerCancelRideView,
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

    # ========================================================
    # PASSENGER
    # ========================================================

    path(
        "rides/create/",
        CreateRideView.as_view(),
        name="create-ride",
    ),

    path(
        "rides/passenger/active/",
        PassengerActiveRidesView.as_view(),
        name="passenger-active-rides",
    ),

    path(
        "rides/<str:ride_id>/",
        PassengerRideDetailView.as_view(),
        name="passenger-ride-detail",
    ),

    path(
        "rides/<str:ride_id>/cancel/",
        PassengerCancelRideView.as_view(),
        name="passenger-cancel-ride",
    ),

    # ========================================================
    # DRIVER
    # ========================================================

    path(
        "rides/available/",
        AvailableRidesView.as_view(),
        name="available-rides",
    ),

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
]