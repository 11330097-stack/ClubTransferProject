from django.views.generic import TemplateView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.contrib.auth import get_user_model
from clubs.models import Club
from transfers.models import TransferRequest


class HomeView(TemplateView):
    """
    系統首頁 - 顯示各社團現有人數、待審核人數及剩餘名額
    """
    template_name = 'accounts/home.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        User = get_user_model()
        pending_statuses = [
            'orig_president_pending',
            'orig_teacher_pending',
            'new_president_pending',
            'new_teacher_pending',
            'admin_pending',
        ]

        context.update({
            'club_count': Club.objects.filter(is_active=True).count(),
            'student_count': User.objects.filter(role='student', is_active=True).count(),
            'pending_count': TransferRequest.objects.filter(status__in=pending_statuses).count(),
        })
        return context


class ProfileView(LoginRequiredMixin, TemplateView):
    """
    個人資料頁面
    """
    template_name = 'accounts/profile.html'
