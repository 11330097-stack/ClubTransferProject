import re

from django.db.models import Count, Q
from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from transfers.models import get_user_from_display_text
from .models import Club


def display_name_without_username(value):
    return re.sub(r'\s*\([^()]+\)\s*$', '', value or '').strip()


class ClubListView(LoginRequiredMixin, ListView):
    """
    社團列表頁面
    """
    model = Club
    template_name = 'clubs/club_list.html'
    context_object_name = 'clubs'
    
    def get_queryset(self):
        queryset = Club.objects.filter(is_active=True).annotate(
            actual_member_count=Count(
                'members',
                filter=Q(
                    members__role__in=['student', 'president'],
                    members__is_active=True,
                ),
            )
        )
        query = self.request.GET.get('q', '').strip()
        if query:
            queryset = queryset.filter(name__icontains=query)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '').strip()
        context['club_name_options'] = Club.objects.filter(
            is_active=True,
        ).order_by('name').values_list('name', flat=True)

        club_info = []
        for club in context['clubs']:
            club_info.append({
                'club': club,
                'teacher_name': display_name_without_username(club.teacher),
                'president_name': display_name_without_username(club.president),
                'actual_member_count': club.actual_member_count,
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
        context['actual_member_count'] = club.get_actual_member_count()
        president = get_user_from_display_text(club.president)
        members = list(club.members.all())
        context['members'] = sorted(
            members,
            key=lambda member: (
                0 if president and member.pk == president.pk else 1,
                member.first_name or member.username,
            ),
        )
        context['teacher_name'] = display_name_without_username(club.teacher)
        context['president_name'] = display_name_without_username(club.president)
        
        return context
