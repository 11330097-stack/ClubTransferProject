from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # 首頁
    path('', views.HomeView.as_view(), name='home'),
    
    # 認證相關
    path('login/', auth_views.LoginView.as_view(
        template_name='accounts/login.html',
        redirect_authenticated_user=True
    ), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    # 使用者資訊
    path('profile/', views.ProfileView.as_view(), name='profile'),
]
