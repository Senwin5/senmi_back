# senmi/urls.py
from django.urls import path
from .views import CreatePackageView, RegisterView, RiderEarningsView, RiderProfileUpdateView
from .views import AvailablePackagesView, AcceptPackageView,UpdateDeliveryStatusView,CustomLoginView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', CustomLoginView.as_view(), name='login'),
    path('rider-profile/', RiderProfileUpdateView.as_view(), name='rider-profile-update'),
    path('packages/', AvailablePackagesView.as_view()),
    path('packages/<int:package_id>/accept/', AcceptPackageView.as_view()),
    path('create-package/', CreatePackageView.as_view()),
    path('packages/<int:package_id>/update-status/', UpdateDeliveryStatusView.as_view()),
    path('rider-earnings/', RiderEarningsView.as_view()),
]