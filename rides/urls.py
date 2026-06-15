from django.urls import path
from .views import (
    about
,
    privacy_policy,
    support,
    terms_conditions,
    home,
    faq,
    contact,
)

urlpatterns = [
    path('', home, name='home'),
    path('home', home, name='home'),

]