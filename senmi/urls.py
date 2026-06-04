# senmi/urls.py
from django.urls import path

from senmi.views import AdminNotificationView
from .views import AdminPackagesView, AdminRidersListView, AdminUserSearchView, AdminWithdrawalsView 
from .views import admin_notifications,delete_package, save_fcm_token, search_package,AvailableRidersView
from .views import AcceptPackageView,UpdateDeliveryStatusView,CustomLoginView,RegisterView,calculate_price_view
from .views import ApproveWithdrawalView, CustomerPackagesView, HardDeleteUserView, RejectWithdrawalView
from .views import AvailablePackagesView,PaystackWebhookView,RiderEarningsView,RiderStatusView,ResolveAccountView, RetryWithdrawalView
from .views import LogoutView, PackageDetailView, PaymentCallbackView, BankListView, CreatePackageView
from .views import RiderProfileUpdateView, RiderWalletView, RiderWithdrawView,RateRiderView, TrackPackageView
from .views import UpdateLocationView, UserProfileView, review_rider, InitializeReceiverPaymentView
from senmi import views


urlpatterns = [
    path('api/register/', RegisterView.as_view(), name='register'),
    path('api/login/', CustomLoginView.as_view(), name='login'),
    path('api/logout/', LogoutView.as_view(), name='logout'),
    path('api/packages/search/', search_package),
    path('api/rider-profile/', RiderProfileUpdateView.as_view(), name='rider-profile-update'),
    path('api/review-rider/<int:rider_id>/', review_rider, name='review-rider'),
    path('api/admin/packages/',AdminPackagesView.as_view()),
    path('api/admin/analytics/',views.admin_analytics,name='admin_analytics'),
    path('api/admin/dashboard/',views.admin_dashboard,name='admin_dashboard'),
    path('api/admin/available-riders/',AvailableRidersView.as_view(),),
    path("api/admin/customers/",views.admin_customers,),
    path("api/admin/customers/<int:customer_id>/",views.admin_customer_detail,),
    path('api/packages/', AvailablePackagesView.as_view()),
    path('api/packages/<str:package_id>/accept/', AcceptPackageView.as_view()),
    path('api/create-package/', CreatePackageView.as_view()),
    path('api/packages/<str:package_id>/update-status/', UpdateDeliveryStatusView.as_view()),
    path('api/rider-earnings/', RiderEarningsView.as_view()),
    path('api/rider/my-packages/', views.RiderActivePackagesView.as_view()),
    path('api/my-orders/', views.my_orders),
    path('api/packages/<str:package_id>/pay/', InitializeReceiverPaymentView.as_view()),
    path('api/paystack/webhook/', PaystackWebhookView.as_view()),
    path('api/payment/callback/', PaymentCallbackView.as_view()),
    path('api/packages/<str:package_id>/update-location/', UpdateLocationView.as_view()),
    path('api/track/<str:package_id>/', TrackPackageView.as_view()),
    path('api/rider/wallet/', RiderWalletView.as_view()),
    path('api/rider/wallet/withdraw/', RiderWithdrawView.as_view()),
    path('api/banks/', BankListView.as_view()),
    path('rider/resolve-account/', ResolveAccountView.as_view()),
    path('api/customer/packages/', CustomerPackagesView.as_view()),
    path('api/packages/<str:package_id>/', PackageDetailView.as_view()),
    path('api/packages/<str:package_id>/rate/', RateRiderView.as_view()),
    path('api/search-users/', AdminUserSearchView.as_view()),
    path('api/admin/riders/', AdminRidersListView.as_view()),
    path('api/rider/status/', RiderStatusView.as_view(), name='rider-status'),
    path('api/profile/', UserProfileView.as_view()),
    path('api/profile/hard-delete/', HardDeleteUserView.as_view()),
    path('api/calculate-price/', calculate_price_view),
    path('api/packages/<str:package_id>/delete/', delete_package),
    path('api/admin/withdrawals/', AdminWithdrawalsView.as_view()),
    path('api/admin/withdrawals/<int:withdrawal_id>/approve/',ApproveWithdrawalView.as_view()),
    path('api/admin/withdrawals/<int:withdrawal_id>/reject/',RejectWithdrawalView.as_view()),
    path('api/admin/withdrawals/<int:withdrawal_id>/retry/',RetryWithdrawalView.as_view()),
    path('api/payment-success/', views.payment_success),
    path('api/save-fcm-token/', save_fcm_token),
    path("api/send-notification/",AdminNotificationView.as_view(),name="admin-send-notification"),
    path("api/admin-notifications/",admin_notifications,name="admin-notifications"),
    path("api/admin/customers/",views.admin_customers,name="admin_customers",)
 
    
]