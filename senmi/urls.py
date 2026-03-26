# senmi/urls.py
from django.urls import path
from .views import CreatePackageView, CustomerPackagesView, InitializeReceiverPaymentView, UpdateLocationView
from .views import AcceptPackageView,UpdateDeliveryStatusView,CustomLoginView,RegisterView
from .views import AvailablePackagesView,PaystackWebhookView,RiderEarningsView
from .views import RiderProfileUpdateView, RiderWalletView, RiderWithdrawView,RateRiderView,  TrackPackageView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', CustomLoginView.as_view(), name='login'),
    path('rider-profile/', RiderProfileUpdateView.as_view(), name='rider-profile-update'),
    path('packages/', AvailablePackagesView.as_view()),
    path('packages/<int:package_id>/accept/', AcceptPackageView.as_view()),
    path('create-package/', CreatePackageView.as_view()),
    path('packages/<int:package_id>/update-status/', UpdateDeliveryStatusView.as_view()),
    path('rider-earnings/', RiderEarningsView.as_view()),
    path('packages/<int:package_id>/pay/', InitializeReceiverPaymentView.as_view()),
    path('paystack/webhook/', PaystackWebhookView.as_view()),
    path('packages/<int:package_id>/update-location/', UpdateLocationView.as_view()),
    path('packages/<int:package_id>/track/', TrackPackageView.as_view()),
    path('rider/wallet/', RiderWalletView.as_view()),
    path('rider/wallet/withdraw/', RiderWithdrawView.as_view()),
    path('customer/packages/', CustomerPackagesView.as_view()),
    path('packages/<int:package_id>/rate/', RateRiderView.as_view()),
]