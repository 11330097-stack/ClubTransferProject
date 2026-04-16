from django.urls import path
from . import views

urlpatterns = [
    path('', views.ClubListView.as_view(), name='club_list'),
    path('<int:pk>/', views.ClubDetailView.as_view(), name='club_detail'),
]
