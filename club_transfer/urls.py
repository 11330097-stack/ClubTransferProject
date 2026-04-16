"""
URL configuration for club_transfer project.
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('accounts.urls')),
    path('clubs/', include('clubs.urls')),
    path('transfers/', include('transfers.urls')),
]
