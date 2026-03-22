# senmi/urls.py
from django.urls import path
from .views import RegisterView, RiderProfileUpdateView, CustomLoginView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', CustomLoginView.as_view(), name='login'),
    path('rider-profile/', RiderProfileUpdateView.as_view(), name='rider-profile-update'),
]