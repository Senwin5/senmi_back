from django.urls import path

from .views import (
    RideDriverProfileView,
    CreateRideView,
    PassengerActiveRidesView,
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


urlpatterns = [

    # ========================================================
    # DRIVER PROFILE
    # ========================================================

    path(
        "driver/profile/",
        RideDriverProfileView.as_view(),
        name="ride-driver-profile"
    ),

    # ========================================================
    # PASSENGER RIDES
    # ========================================================

    path(
        "rides/create/",
        CreateRideView.as_view(),
        name="create-ride"
    ),

    path(
        "rides/passenger/active/",
        PassengerActiveRidesView.as_view(),
        name="passenger-active-rides"
    ),

    # ========================================================
    # DRIVER RIDES
    # ========================================================

    path(
        "rides/available/",
        AvailableRidesView.as_view(),
        name="available-rides"
    ),

    path(
        "rides/<str:ride_id>/accept/",
        AcceptRideView.as_view(),
        name="accept-ride"
    ),

    path(
        "rides/driver/active/",
        DriverActiveRidesView.as_view(),
        name="driver-active-rides"
    ),

    # ========================================================
    # RIDE STATUS
    # ========================================================

    path(
        "rides/<str:ride_id>/status/",
        UpdateRideStatusView.as_view(),
        name="update-ride-status"
    ),

    # ========================================================
    # RIDE TRACKING
    # ========================================================

    path(
        "rides/<str:ride_id>/tracking/",
        RideTrackingView.as_view(),
        name="ride-tracking"
    ),

    # ========================================================
    # RATING
    # ========================================================

    path(
        "rides/<str:ride_id>/rating/",
        RideRatingView.as_view(),
        name="ride-rating"
    ),

    # ========================================================
    # DRIVER WALLET
    # ========================================================

    path(
        "driver/wallet/",
        RideDriverWalletView.as_view(),
        name="ride-driver-wallet"
    ),

    # ========================================================
    # DRIVER → SENMI COMMISSION
    # ========================================================

    path(
        "commission/pay/",
        RideCommissionPaymentView.as_view(),
        name="ride-commission-pay"
    ),

    # ========================================================
    # VERIFY PAYSTACK COMMISSION
    # ========================================================

    path(
        "commission/verify/<str:reference>/",
        VerifyRideCommissionPaymentView.as_view(),
        name="verify-ride-commission"
    ),

]