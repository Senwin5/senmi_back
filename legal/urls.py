from django.urls import path
from .views import privacy_policy, terms_conditions

urlpatterns = [
    path('privacy/', privacy_policy, name='privacy'),
    path('terms/', terms_conditions, name='terms'),
]