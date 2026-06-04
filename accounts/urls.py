from django.contrib.auth import views as auth_views
from django.urls import path

from . import views


urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('login/', auth_views.LoginView.as_view(
        template_name='accounts/login.html',
        redirect_authenticated_user=True,
    ), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('admin-panel/unassigned/accounts/', views.UnassignedAccountListView.as_view(), name='unassigned_account_list'),
    path('admin-panel/unassigned/students/<int:pk>/assign-club/', views.UnassignedStudentAssignClubView.as_view(), name='unassigned_student_assign_club'),
    path('admin-panel/clubs/', views.ClubAdminListView.as_view(), name='club_admin_list'),
    path('admin-panel/clubs/create/', views.ClubAdminCreateView.as_view(), name='club_admin_create'),
    path('admin-panel/clubs/import/', views.ClubCsvImportView.as_view(), name='club_admin_import'),
    path('admin-panel/clubs/<int:pk>/edit/', views.ClubAdminUpdateView.as_view(), name='club_admin_edit'),
    path('admin-panel/clubs/<int:pk>/delete/', views.ClubAdminDeleteView.as_view(), name='club_admin_delete'),
    path('admin-panel/students/', views.StudentAdminListView.as_view(), name='student_admin_list'),
    path('admin-panel/students/create/', views.StudentAdminCreateView.as_view(), name='student_admin_create'),
    path('admin-panel/students/bulk/deactivate/', views.StudentAdminBulkDeactivateView.as_view(), name='student_admin_bulk_deactivate'),
    path('admin-panel/students/bulk/reactivate/', views.StudentAdminBulkReactivateView.as_view(), name='student_admin_bulk_reactivate'),
    path('admin-panel/students/bulk/delete/confirm/', views.StudentAdminBulkDeleteConfirmView.as_view(), name='student_admin_bulk_delete_confirm'),
    path('admin-panel/students/bulk/delete/', views.StudentAdminBulkDeleteView.as_view(), name='student_admin_bulk_delete'),
    path('admin-panel/students/<int:pk>/edit/', views.StudentAdminUpdateView.as_view(), name='student_admin_edit'),
    path('admin-panel/students/<int:pk>/deactivate/', views.StudentAdminDeactivateView.as_view(), name='student_admin_deactivate'),
    path('admin-panel/students/<int:pk>/reactivate/', views.StudentAdminReactivateView.as_view(), name='student_admin_reactivate'),
    path('admin-panel/students/<int:pk>/delete/', views.StudentAdminDeleteView.as_view(), name='student_admin_delete'),
    path('admin-panel/students/<int:pk>/promote-president/', views.StudentAdminPromotePresidentView.as_view(), name='student_admin_promote_president'),
    path('admin-panel/students/import/', views.StudentCsvImportView.as_view(), name='student_admin_import'),
]
