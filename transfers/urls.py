from django.urls import path
from . import views

urlpatterns = [
    # 學生功能
    path('apply/', views.TransferApplyView.as_view(), name='transfer_apply'),
    path('my-requests/', views.MyRequestsView.as_view(), name='my_requests'),
    path('request/<int:pk>/', views.RequestDetailView.as_view(), name='request_detail'),
    path('request/<int:pk>/reselect/', views.ReselectClubView.as_view(), name='reselect_club'),
    
    # 審核功能
    path('pending/', views.PendingApprovalsView.as_view(), name='pending_approvals'),
    path('request/<int:pk>/approve/', views.ApproveRequestView.as_view(), name='approve_request'),
    path('request/<int:pk>/reject/', views.RejectRequestView.as_view(), name='reject_request'),
    
    # 管理員功能
    path('all-requests/', views.AllRequestsView.as_view(), name='all_requests'),
]
