# senmi/urls.py

from django.urls import path
from .views import RegisterView, RiderProfileUpdateView

urlpatterns = [
    path('register/', RegisterView.as_view()),
    path('rider/profile/update/', RiderProfileUpdateView.as_view()),
]