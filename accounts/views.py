from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView, View

from clubs.models import Club
from transfers.models import ApprovalLog, TransferRequest
from .forms import ClubAdminForm, StudentAccountForm, StudentCsvImportForm
from .models import User
from .services import (
    SAMPLE_STUDENT_IMPORT_CSV,
    import_students_from_csv,
    recalculate_club_current_members,
)


class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (
            user.is_superuser or getattr(user, 'role', None) == 'admin'
        )


class HomeView(TemplateView):
    template_name = 'accounts/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        UserModel = get_user_model()
        pending_statuses = [
            'orig_president_pending',
            'orig_teacher_pending',
            'new_president_pending',
            'new_teacher_pending',
            'admin_pending',
        ]

        context.update({
            'club_count': Club.objects.filter(is_active=True).count(),
            'student_count': UserModel.objects.filter(role='student', is_active=True).count(),
            'pending_count': TransferRequest.objects.filter(status__in=pending_statuses).count(),
        })
        return context


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = 'accounts/profile.html'


class ClubAdminListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = Club
    template_name = 'accounts/club_admin_list.html'
    context_object_name = 'clubs'
    paginate_by = 50

    def get_queryset(self):
        queryset = Club.objects.all().order_by('code', 'name')
        query = self.request.GET.get('q', '').strip()
        if query:
            queryset = queryset.filter(
                Q(code__icontains=query)
                | Q(name__icontains=query)
                | Q(teacher__icontains=query)
                | Q(president__icontains=query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '').strip()
        return context


class ClubAdminCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = Club
    form_class = ClubAdminForm
    template_name = 'accounts/club_admin_form.html'
    success_url = reverse_lazy('club_admin_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        recalculate_club_current_members()
        messages.success(self.request, '社團已新增。')
        return response


class ClubAdminUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = Club
    form_class = ClubAdminForm
    template_name = 'accounts/club_admin_form.html'
    success_url = reverse_lazy('club_admin_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        recalculate_club_current_members()
        messages.success(self.request, '社團資料已更新。')
        return response


class ClubAdminDeactivateView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'accounts/club_admin_confirm_deactivate.html'

    def get(self, request, pk):
        club = get_object_or_404(Club, pk=pk)
        active_member_count = self.get_active_member_count(club)
        return render(
            request,
            self.template_name,
            {'club': club, 'active_member_count': active_member_count},
        )

    def post(self, request, pk):
        club = get_object_or_404(Club, pk=pk)
        active_member_count = self.get_active_member_count(club)
        if active_member_count > 0:
            messages.error(
                request,
                '此社團仍有啟用中的學生或社長，請先移出或停用相關帳號後再停用社團。',
            )
            return redirect('club_admin_list')

        club.is_active = False
        club.save(update_fields=['is_active'])
        recalculate_club_current_members()
        messages.success(request, '社團已停用。')
        return redirect('club_admin_list')

    def get_active_member_count(self, club):
        return User.objects.filter(
            club=club,
            is_active=True,
            role__in=['student', 'president'],
        ).count()


class ClubAdminReactivateView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk):
        club = get_object_or_404(Club, pk=pk)
        club.is_active = True
        club.save(update_fields=['is_active'])
        recalculate_club_current_members()
        messages.success(request, '社團已重新啟用。')
        return redirect('club_admin_list')


class StudentAdminListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = User
    template_name = 'accounts/student_admin_list.html'
    context_object_name = 'students'
    paginate_by = 50

    def get_queryset(self):
        queryset = User.objects.filter(role='student').select_related('club').order_by('username')
        query = self.request.GET.get('q', '').strip()
        if query:
            queryset = queryset.filter(
                Q(username__icontains=query)
                | Q(student_id__icontains=query)
                | Q(first_name__icontains=query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '').strip()
        return context


class StudentAdminCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = User
    form_class = StudentAccountForm
    template_name = 'accounts/student_admin_form.html'
    success_url = reverse_lazy('student_admin_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['is_create'] = True
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        recalculate_club_current_members()
        messages.success(self.request, '學生帳號已新增。')
        return response


class StudentAdminUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = User
    form_class = StudentAccountForm
    template_name = 'accounts/student_admin_form.html'
    success_url = reverse_lazy('student_admin_list')

    def get_queryset(self):
        return User.objects.filter(role='student')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['is_create'] = False
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        recalculate_club_current_members()
        messages.success(self.request, '學生資料已更新。')
        return response


class StudentAdminDeactivateView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'accounts/student_admin_confirm_deactivate.html'

    def get(self, request, pk):
        student = get_object_or_404(User, pk=pk, role='student')
        return render(request, self.template_name, {'student': student})

    def post(self, request, pk):
        student = get_object_or_404(User, pk=pk, role='student')
        student.is_active = False
        student.save(update_fields=['is_active'])
        recalculate_club_current_members()
        messages.success(request, '學生帳號已停用。')
        return redirect('student_admin_list')


class StudentAdminReactivateView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk):
        student = get_object_or_404(User, pk=pk, role='student')
        student.is_active = True
        student.save(update_fields=['is_active'])
        recalculate_club_current_members()
        messages.success(request, '學生帳號已重新啟用。')
        return redirect('student_admin_list')


class StudentAdminDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'accounts/student_admin_confirm_delete.html'

    def get(self, request, pk):
        student = get_object_or_404(User, pk=pk, role='student')
        return render(request, self.template_name, {'student': student})

    def post(self, request, pk):
        student = get_object_or_404(User, pk=pk, role='student')

        with transaction.atomic():
            has_history = self.has_student_history(student)
            if has_history:
                if student.is_active:
                    student.is_active = False
                    student.save(update_fields=['is_active'])
                messages.warning(
                    request,
                    '此學生已有申請或審核紀錄，為保留歷史資料，系統已改為停用而非刪除。',
                )
            else:
                student.delete()
                messages.success(request, '學生帳號已刪除。')

            recalculate_club_current_members()

        return redirect('student_admin_list')

    def has_student_history(self, student):
        has_transfer_requests = TransferRequest.objects.filter(student=student).exists()
        has_approval_logs = ApprovalLog.objects.filter(
            Q(transfer_request__student=student) | Q(approver=student)
        ).exists()
        return has_transfer_requests or has_approval_logs


class StudentCsvImportView(LoginRequiredMixin, AdminRequiredMixin, FormView):
    template_name = 'accounts/student_admin_import.html'
    form_class = StudentCsvImportForm
    success_url = reverse_lazy('student_admin_import')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sample_csv'] = SAMPLE_STUDENT_IMPORT_CSV
        context['result'] = getattr(self, 'result', None)
        return context

    def form_valid(self, form):
        self.result = import_students_from_csv(form.cleaned_data['csv_file'])
        return self.render_to_response(self.get_context_data(form=form))
