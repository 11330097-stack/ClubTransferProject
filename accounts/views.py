from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView, View

from clubs.models import Club
from transfers.models import get_user_from_display_text
from transfers.models import TransferRequest
from .forms import (
    ClubAdminForm,
    StudentAccountForm,
    StudentCsvImportForm,
    get_teacher_match_values,
    normalize_teacher_text,
)
from .models import User
from .services import (
    SAMPLE_STUDENT_IMPORT_CSV,
    import_students_from_csv,
    recalculate_club_current_members,
    safely_delete_student,
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


class UnassignedAccountListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    template_name = 'accounts/unassigned_account_list.html'
    context_object_name = 'accounts'
    paginate_by = 50

    def get_queryset(self):
        query = self.request.GET.get('q', '').strip()

        student_accounts = User.objects.filter(
            role='student',
            is_active=True,
            club__isnull=True,
        )
        teacher_accounts = User.objects.filter(role='teacher', is_active=True)

        if query:
            search_filter = (
                Q(username__icontains=query)
                | Q(student_id__icontains=query)
                | Q(first_name__icontains=query)
                | Q(email__icontains=query)
            )
            student_accounts = student_accounts.filter(search_filter)
            teacher_accounts = teacher_accounts.filter(search_filter)

        assigned_teacher_values = {
            normalize_teacher_text(value)
            for value in Club.objects.exclude(teacher='').values_list('teacher', flat=True)
            if normalize_teacher_text(value)
        }

        accounts = list(student_accounts) + [
            teacher for teacher in teacher_accounts
            if get_teacher_match_values(teacher).isdisjoint(assigned_teacher_values)
        ]
        return sorted(accounts, key=lambda account: (account.role, account.username))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '').strip()
        context['active_clubs'] = Club.objects.filter(is_active=True).order_by('code', 'name')
        return context


class UnassignedStudentAssignClubView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk):
        student = get_object_or_404(
            User,
            pk=pk,
            role='student',
            is_active=True,
            club__isnull=True,
        )
        club = get_object_or_404(Club, pk=request.POST.get('club_id'), is_active=True)

        with transaction.atomic():
            student.club = club
            student.save(update_fields=['club'])
            recalculate_club_current_members()

        messages.success(request, f'已將 {student.username} 分配到 {club.name}。')
        return redirect('unassigned_account_list')


class ClubAdminListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = Club
    template_name = 'accounts/club_admin_list.html'
    context_object_name = 'clubs'
    paginate_by = 50

    def get_queryset(self):
        queryset = Club.objects.filter(is_active=True).order_by('code', 'name')
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
        with transaction.atomic():
            self.object = form.save()
            president = User.objects.select_for_update().get(pk=form.selected_president.pk)
            president.role = 'president'
            president.club = self.object
            president.save(update_fields=['role', 'club'])
            recalculate_club_current_members()

        messages.success(self.request, '社團已新增。')
        return redirect(self.get_success_url())


class ClubAdminUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = Club
    form_class = ClubAdminForm
    template_name = 'accounts/club_admin_form.html'
    success_url = reverse_lazy('club_admin_list')

    def form_valid(self, form):
        previous_president_text = Club.objects.only('president').get(pk=self.object.pk).president
        previous_president = get_user_from_display_text(previous_president_text)
        previous_president_ids = list(
            User.objects.filter(club=self.object, role='president').values_list('pk', flat=True)
        )
        if previous_president and previous_president.role == 'president':
            previous_president_ids.append(previous_president.pk)

        with transaction.atomic():
            self.object = form.save()
            new_president = User.objects.select_for_update().get(pk=form.selected_president.pk)

            User.objects.filter(
                pk__in=previous_president_ids,
            ).exclude(pk=new_president.pk).update(role='student', club=self.object)

            new_president.role = 'president'
            new_president.club = self.object
            new_president.save(update_fields=['role', 'club'])
            recalculate_club_current_members()

        messages.success(self.request, '社團資料已更新。')
        return redirect(self.get_success_url())


class ClubAdminDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'accounts/club_admin_confirm_delete.html'

    def get(self, request, pk):
        club = get_object_or_404(Club, pk=pk)
        active_members = self.get_active_members(club)
        return render(
            request,
            self.template_name,
            {
                'club': club,
                'active_member_count': active_members.count(),
                'active_members': active_members[:10],
            },
        )

    def post(self, request, pk):
        club = get_object_or_404(Club, pk=pk)

        with transaction.atomic():
            president = get_user_from_display_text(club.president)
            president_ids = list(
                User.objects.filter(club=club, role='president').values_list('pk', flat=True)
            )
            if president and president.role == 'president':
                president_ids.append(president.pk)

            released_count = User.objects.filter(club=club).count()
            User.objects.filter(pk__in=president_ids).update(role='student', club=None)
            User.objects.filter(club=club).update(club=None)
            club.teacher = ''
            club.president = ''
            club.is_active = False
            club.save(update_fields=['teacher', 'president', 'is_active'])
            recalculate_club_current_members()

        messages.warning(
            request,
            f'社團已安全刪除：已停用社團、清空老師與社長欄位，並解除 {released_count} 位啟用成員的社團分配。',
        )
        return redirect('club_admin_list')

    def get_active_members(self, club):
        return User.objects.filter(
            club=club,
            is_active=True,
            role__in=['student', 'president'],
        ).order_by('role', 'username')


class StudentAdminListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = User
    template_name = 'accounts/student_admin_list.html'
    context_object_name = 'students'
    paginate_by = 50

    def get_queryset(self):
        queryset = User.objects.filter(
            role__in=['student', 'president'],
        ).select_related('club').order_by('username')
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
        return User.objects.filter(role__in=['student', 'president'])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['is_create'] = False
        return kwargs

    def form_valid(self, form):
        original_user = User.objects.only('role', 'username').get(pk=self.object.pk)
        was_president = original_user.role == 'president'
        username_marker = f'({original_user.username})'

        with transaction.atomic():
            response = super().form_valid(form)
            if was_president:
                Club.objects.filter(
                    president__icontains=username_marker,
                ).update(president='')
            recalculate_club_current_members()

        if was_president:
            messages.success(self.request, '社長已降級為一般學生，社團社長欄位已清空。')
        else:
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


class StudentAdminBulkMixin:
    def get_selected_students(self, request):
        student_ids = request.POST.getlist('student_ids')
        return User.objects.filter(pk__in=student_ids, role='student').order_by('username')


class StudentAdminBulkDeactivateView(
    LoginRequiredMixin,
    AdminRequiredMixin,
    StudentAdminBulkMixin,
    View,
):
    def post(self, request):
        students = self.get_selected_students(request)
        with transaction.atomic():
            updated_count = students.update(is_active=False)
            recalculate_club_current_members()

        messages.success(request, f'已批次停用 {updated_count} 位學生。')
        return redirect('student_admin_list')


class StudentAdminBulkReactivateView(
    LoginRequiredMixin,
    AdminRequiredMixin,
    StudentAdminBulkMixin,
    View,
):
    def post(self, request):
        students = self.get_selected_students(request)
        with transaction.atomic():
            updated_count = students.update(is_active=True)
            recalculate_club_current_members()

        messages.success(request, f'已批次重新啟用 {updated_count} 位學生。')
        return redirect('student_admin_list')


class StudentAdminBulkDeleteConfirmView(
    LoginRequiredMixin,
    AdminRequiredMixin,
    StudentAdminBulkMixin,
    View,
):
    template_name = 'accounts/student_admin_bulk_confirm_delete.html'

    def post(self, request):
        students = list(self.get_selected_students(request))
        if not students:
            messages.warning(request, '請先選取要刪除的學生。')
            return redirect('student_admin_list')
        return render(request, self.template_name, {'students': students})


class StudentAdminBulkDeleteView(
    LoginRequiredMixin,
    AdminRequiredMixin,
    StudentAdminBulkMixin,
    View,
):
    def post(self, request):
        students = list(self.get_selected_students(request))
        deleted_count = 0
        deactivated_count = 0

        with transaction.atomic():
            for student in students:
                result = safely_delete_student(student)
                if result == 'deleted':
                    deleted_count += 1
                else:
                    deactivated_count += 1
            recalculate_club_current_members()

        messages.success(
            request,
            f'批次刪除完成：刪除 {deleted_count} 位學生，'
            f'因有歷史紀錄而停用 {deactivated_count} 位學生。',
        )
        return redirect('student_admin_list')


class StudentAdminDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'accounts/student_admin_confirm_delete.html'

    def get(self, request, pk):
        student = get_object_or_404(User, pk=pk, role='student')
        return render(request, self.template_name, {'student': student})

    def post(self, request, pk):
        student = get_object_or_404(User, pk=pk, role='student')

        with transaction.atomic():
            result = safely_delete_student(student)
            if result == 'deactivated':
                messages.warning(
                    request,
                    '此學生已有申請或審核紀錄，為保留歷史資料，系統已改為停用而非刪除。',
                )
            else:
                messages.success(request, '學生帳號已刪除。')

            recalculate_club_current_members()

        return redirect('student_admin_list')

class StudentAdminPromotePresidentView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk):
        student = get_object_or_404(User.objects.select_related('club'), pk=pk)

        if student.role == 'president':
            messages.warning(request, '此學生已經是社長，無法重複晉升。')
            return redirect('student_admin_list')

        if student.role != 'student':
            messages.error(request, '只有一般學生可以晉升為社長。')
            return redirect('student_admin_list')

        if not student.club_id:
            messages.error(request, '此學生目前沒有社團，無法晉升為社長。')
            return redirect('student_admin_list')

        with transaction.atomic():
            student = User.objects.select_for_update().select_related('club').get(pk=student.pk)
            club = Club.objects.select_for_update().get(pk=student.club_id)
            previous_president = get_user_from_display_text(club.president)

            if previous_president and previous_president.pk != student.pk:
                previous_president = User.objects.select_for_update().get(pk=previous_president.pk)
                previous_president.role = 'student'
                previous_president.club = club
                previous_president.save(update_fields=['role', 'club'])

            student.role = 'president'
            student.club = club
            student.save(update_fields=['role', 'club'])

            display_name = student.get_full_name() or student.first_name or student.username
            club.president = f'{display_name} ({student.username})'
            club.save(update_fields=['president'])

            recalculate_club_current_members()

        messages.success(request, f'{display_name} 已晉升為 {club.name} 社長。')
        return redirect('student_admin_list')


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
