from django.urls import path
from . import views

urlpatterns = [
    # Student actions
    path('apply/', views.TransferApplyView.as_view(), name='transfer_apply'),
    path('my-requests/', views.MyRequestsView.as_view(), name='my_requests'),
    path('request/<int:pk>/', views.RequestDetailView.as_view(), name='request_detail'),
    path('request/<int:pk>/reselect/', views.ReselectClubView.as_view(), name='reselect_club'),
    path('request/<int:pk>/delete/', views.DeleteRequestRecordView.as_view(), name='delete_request_record'),

    # Review actions
    path('pending/', views.PendingApprovalsView.as_view(), name='pending_approvals'),
    path('request/<int:pk>/approve/', views.ApproveRequestView.as_view(), name='approve_request'),
    path('request/<int:pk>/reject/', views.RejectRequestView.as_view(), name='reject_request'),

    # Admin actions
    path('all-requests/', views.AllRequestsView.as_view(), name='all_requests'),
    path('all-requests/delete-all/', views.DeleteAllRequestRecordsView.as_view(), name='delete_all_request_records'),
]
