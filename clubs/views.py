from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Club


class ClubListView(LoginRequiredMixin, ListView):
    """
    社團列表頁面
    """
    model = Club
    template_name = 'clubs/club_list.html'
    context_object_name = 'clubs'
    
    def get_queryset(self):
        return Club.objects.filter(is_active=True).prefetch_related('transfer_in_requests')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        club_info = []
        for club in context['clubs']:
            pending_count = club.transfer_in_requests.filter(
                status__in=['new_president_pending', 'new_teacher_pending']
            ).count()

            club_info.append({
                'club': club,
                'pending_count': pending_count,
                'remaining_slots': club.get_remaining_slots(),
            })

        context['club_info_list'] = club_info
        return context


class ClubDetailView(LoginRequiredMixin, DetailView):
    """
    社團詳細資訊頁面
    """
    model = Club
    template_name = 'clubs/club_detail.html'
    context_object_name = 'club'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        club = self.object
        
        # 取得待審核人數
        pending_count = club.transfer_in_requests.filter(
            status__in=['new_president_pending', 'new_teacher_pending']
        ).count()
        
        context['pending_count'] = pending_count
        context['remaining_slots'] = club.get_remaining_slots()
        context['members'] = club.members.all()
        
        return context
