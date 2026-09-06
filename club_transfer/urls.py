"""
URL configuration for club_transfer project.
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView


handler403 = 'club_transfer.error_views.permission_denied'
handler404 = 'club_transfer.error_views.page_not_found'
handler500 = 'club_transfer.error_views.server_error'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('accounts.urls')),
    path('clubs/', include('clubs.urls')),
    path('transfers/', include('transfers.urls')),
]
