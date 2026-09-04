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
    RideDriverBankView,
    RideWithdrawalView,
)


urlpatterns = [

    # Driver profile
    path("driver/profile/",RideDriverProfileView.as_view(),name="ride-driver-profile"),
    # Passenger rides
    path("rides/create/",CreateRideView.as_view(),name="create-ride"),
    path("rides/passenger/active/",PassengerActiveRidesView.as_view(),name="passenger-active-rides"),
    # Driver rides
    path("rides/available/",AvailableRidesView.as_view(),name="available-rides"),
    path("rides/<str:ride_id>/accept/",AcceptRideView.as_view(),name="accept-ride"),
    path("rides/driver/active/",DriverActiveRidesView.as_view(),name="driver-active-rides"),
    # Ride status
    path("rides/<str:ride_id>/status/",UpdateRideStatusView.as_view(),name="update-ride-status"),
    # Tracking
    path("rides/<str:ride_id>/tracking/",RideTrackingView.as_view(),name="ride-tracking"),
    # Rating
    path("rides/<str:ride_id>/rating/",RideRatingView.as_view(),name="ride-rating"),
    # Driver wallet
    path("driver/wallet/",RideDriverWalletView.as_view(),name="ride-driver-wallet"),
    # Driver bank
    path("driver/bank/",RideDriverBankView.as_view(),name="ride-driver-bank"),
    # Withdrawals
    path("driver/withdrawals/",RideWithdrawalView.as_view(),name="ride-withdrawals"),
    
]