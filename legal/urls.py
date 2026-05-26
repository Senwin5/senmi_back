from django.urls import path
from .views import (
    about
,
    privacy_policy,
    terms_conditions,
    home,
    faq,
    contact,
)

urlpatterns = [
    path('', home, name='home'),
    path('home', home, name='home'),
    path('about/', about, name='about'),
    path('privacy/', privacy_policy, name='privacy'),
    path('terms/', terms_conditions, name='terms'),
    path('faq/', faq, name='faq'),
    path('contact/', contact, name='contact'),
]