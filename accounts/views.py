from django.views.generic import TemplateView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from clubs.models import Club


class HomeView(TemplateView):
    """
    系統首頁 - 顯示各社團現有人數、待審核人數及剩餘名額
    """
    template_name = 'accounts/home.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        clubs = Club.objects.all().prefetch_related('members', 'transfer_in_requests')
        
        club_info = []
        for club in clubs:
            pending_count = club.transfer_in_requests.filter(
                status__in=['new_president_pending', 'new_teacher_pending']
            ).count()
            
            remaining_slots = club.max_members - club.current_members
            
            club_info.append({
                'club': club,
                'pending_count': pending_count,
                'remaining_slots': max(0, remaining_slots),
            })
        
        context['club_info_list'] = club_info
        return context


class ProfileView(LoginRequiredMixin, TemplateView):
    """
    個人資料頁面
    """
    template_name = 'accounts/profile.html'
