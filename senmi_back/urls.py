from django.contrib import admin
from django.urls import path,include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path ('',include ('senmi.urls')),
    path('', include('legal.urls')),
    path('', include('rides.urls')),
]

admin.site.site_header = "Senmi Admin "
admin.site.site_title = " Senmi Ltd "

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    
