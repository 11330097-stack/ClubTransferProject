import json

from django.contrib import messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView, View

from clubs.models import Club
from transfers.forms import TransferWindowForm
from transfers.models import get_user_from_display_text
from transfers.models import (
    ApprovalLog,
    TransferRecordArchive,
    TransferRecordSnapshot,
    TransferRequest,
    TransferWindow,
)
from transfers.services import get_transfer_window_state
from .forms import (
    AdminProfileForm,
    AccountCreateForm,
    ClubAdminForm,
    ClubCsvImportForm,
    StudentAccountForm,
    StudentCsvImportForm,
    TeacherAccountForm,
    get_teacher_match_values,
    normalize_teacher_text,
)
from .models import User
from .permissions import can_review_transfer_requests
from .services import (
    SAMPLE_CLUB_IMPORT_CSV,
    SAMPLE_STUDENT_IMPORT_CSV,
    deactivate_student,
    deactivate_teacher,
    clear_president_assignment,
    get_valid_club_president,
    get_valid_club_teacher,
    import_clubs_from_csv,
    import_students_from_csv,
    recalculate_club_current_members,
    safely_delete_student,
    safely_delete_teacher,
)


ASSIGNMENT_LOG_MARKER = 'unassigned_account_assignment'
ACTIVE_TRANSFER_STATUSES = [
    'orig_president_pending',
    'orig_teacher_pending',
    'new_president_pending',
    'new_teacher_pending',
    'admin_pending',
    'returned',
]


class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (
            user.is_superuser or getattr(user, 'role', None) == 'admin'
        )


def should_return_to_account_admin(request):
    if request.POST.get('next') == 'account_admin_list':
        return True
    if request.GET.get('next') == 'account_admin_list':
        return True

    referer = request.META.get('HTTP_REFERER', '')
    return reverse('account_admin_list') in referer


def admin_operation_return_url(request, default_url_name):
    if should_return_to_account_admin(request):
        return reverse('account_admin_list')
    return reverse(default_url_name)


def format_club_user_display_text(user):
    display_name = user.get_full_name() or user.first_name or user.username
    return f'{display_name} ({user.username})'


def is_club_president_user(user, club):
    if not user or not club or not club.president:
        return False
    president = get_user_from_display_text(club.president)
    if president:
        return president.pk == user.pk
    return club.president.strip() == user.username


def get_club_president_ids(club):
    president_ids = set(
        User.objects.filter(club=club, role='president').values_list('pk', flat=True)
    )
    president = get_user_from_display_text(club.president)
    if president:
        president_ids.add(president.pk)
    return president_ids


def demote_other_club_presidents(club, new_president=None):
    queryset = User.objects.filter(club=club, role='president')
    if new_president:
        queryset = queryset.exclude(pk=new_president.pk)
    queryset.update(role='student')


def release_club_members(club):
    president_ids = get_club_president_ids(club)
    if president_ids:
        User.objects.filter(pk__in=president_ids).update(role='student', club=None)
    User.objects.filter(club=club).update(club=None)
    club.president = ''
    club.current_members = 0
    club.save(update_fields=['president', 'current_members'])


def reject_active_transfers_for_club(club):
    now = timezone.now()
    return TransferRequest.objects.filter(
        Q(original_club=club) | Q(target_club=club),
        status__in=ACTIVE_TRANSFER_STATUSES,
    ).update(status='rejected', completed_at=now, updated_at=now)


def deactivate_club(club):
    reject_active_transfers_for_club(club)
    release_club_members(club)
    club.is_active = False
    club.save(update_fields=['is_active'])


def safely_delete_club(club):
    has_transfer_history = TransferRequest.objects.filter(
        Q(original_club=club) | Q(target_club=club)
    ).exists()
    reject_active_transfers_for_club(club)
    release_club_members(club)
    club.teacher = ''
    if has_transfer_history:
        club.is_active = False
        club.save(update_fields=['teacher', 'is_active'])
        return 'deactivated'
    club.delete()
    return 'deleted'


def reactivate_club(club):
    if not get_valid_club_president(club) or not get_valid_club_teacher(club):
        return False
    club.is_active = True
    club.current_members = 0
    club.save(update_fields=['is_active', 'current_members'])
    return True


class AccountAdminReturnMixin:
    default_success_url_name = None

    def get_success_url(self):
        return admin_operation_return_url(self.request, self.default_success_url_name)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['return_to_account_admin'] = should_return_to_account_admin(self.request)
        return context


class HomeView(TemplateView):
    template_name = 'accounts/home.html'

    @staticmethod
    def clubs_with_members(queryset):
        return queryset.annotate(
            actual_members=Count(
                'members',
                filter=Q(
                    members__role__in=['student', 'president'],
                    members__is_active=True,
                ),
            ),
        )

    def pending_for_user(self, user):
        queryset = TransferRequest.objects.select_related(
            'student', 'original_club', 'target_club',
        )
        if user.is_superuser or user.role == 'admin':
            return queryset.filter(status='admin_pending')
        username_marker = f'({user.username})'
        if user.role == 'president' and user.club_id:
            return queryset.filter(
                Q(
                    status='orig_president_pending',
                    original_club_id=user.club_id,
                    original_club__president__icontains=username_marker,
                )
                | Q(
                    status='new_president_pending',
                    target_club_id=user.club_id,
                    target_club__president__icontains=username_marker,
                ),
            ).distinct()
        if user.role == 'teacher':
            return queryset.filter(
                Q(
                    status='orig_teacher_pending',
                    original_club__teacher__icontains=username_marker,
                )
                | Q(
                    status='new_teacher_pending',
                    target_club__teacher__icontains=username_marker,
                ),
            ).distinct()
        return queryset.none()

    def add_window_context(self, context):
        state = get_transfer_window_state()
        context.update(state)
        transfer_window = state['transfer_window']
        context['window_timing_text'] = ''
        context['window_days_remaining'] = None
        if not transfer_window:
            return
        today = timezone.localdate()
        status = state['transfer_window_status']
        if status == 'open':
            days = (transfer_window.end_date - today).days
            context['window_days_remaining'] = days
            context['window_timing_text'] = f'距離截止還有 {days} 天' if days else '今天截止'
        elif status == 'not_started':
            days = (transfer_window.start_date - today).days
            context['window_timing_text'] = f'{days} 天後開放' if days else '今天開放'
        elif status == 'paused':
            context['window_timing_text'] = '目前暫停接受新申請'
        else:
            context['window_timing_text'] = '本次申請期間已結束'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        self.add_window_context(context)
        user = self.request.user
        context['dashboard_role'] = 'public'

        if not user.is_authenticated:
            context['club_count'] = Club.objects.filter(is_active=True).count()
            return context

        if user.is_superuser or user.role == 'admin':
            context['dashboard_role'] = 'admin'
            active_clubs = self.clubs_with_members(Club.objects.filter(is_active=True))
            capacity_attention = []
            full_club_count = 0
            for club in active_clubs.order_by('-actual_members', 'name'):
                club.remaining_slots = max(club.max_members - club.actual_members, 0)
                club.capacity_percent = round((club.actual_members / club.max_members) * 100) if club.max_members else 100
                if club.actual_members >= club.max_members:
                    full_club_count += 1
                if club.capacity_percent >= 80:
                    capacity_attention.append(club)
            admin_pending = self.pending_for_user(user)
            context.update({
                'active_club_count': len(active_clubs),
                'active_student_count': User.objects.filter(
                    role__in=['student', 'president'], is_active=True,
                ).count(),
                'unassigned_student_count': User.objects.filter(
                    role='student', is_active=True, club__isnull=True,
                ).count(),
                'dashboard_pending_count': admin_pending.count(),
                'dashboard_pending_preview': list(admin_pending[:4]),
                'full_club_count': full_club_count,
                'capacity_attention': capacity_attention[:4],
                'recent_requests': list(
                    TransferRequest.objects.select_related(
                        'student', 'original_club', 'target_club',
                    ).order_by('-created_at')[:5]
                ),
            })
            return context

        if user.role == 'student':
            context['dashboard_role'] = 'student'
            context['student_request'] = TransferRequest.objects.filter(
                student=user,
            ).select_related('original_club', 'target_club').first()
            return context

        pending = self.pending_for_user(user)
        context['dashboard_pending_count'] = pending.count()
        context['dashboard_pending_preview'] = list(pending[:4])

        if user.role == 'president':
            context['dashboard_role'] = 'president'
            club = None
            if user.club_id:
                club = self.clubs_with_members(
                    Club.objects.filter(pk=user.club_id, is_active=True),
                ).first()
            if club:
                club.remaining_slots = max(club.max_members - club.actual_members, 0)
                club.capacity_percent = round((club.actual_members / club.max_members) * 100) if club.max_members else 100
            context['managed_club'] = club
            return context

        if user.role == 'teacher':
            context['dashboard_role'] = 'teacher'
            marker = f'({user.username})'
            teacher_clubs = self.clubs_with_members(
                Club.objects.filter(
                    Q(teacher__icontains=marker) | Q(teacher__iexact=user.username),
                    is_active=True,
                ).order_by('name'),
            )
            context['teacher_clubs'] = list(teacher_clubs)
            return context

        return context


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = 'accounts/profile.html'


class ProfilePasswordChangeView(LoginRequiredMixin, FormView):
    template_name = 'accounts/profile_password_change.html'
    form_class = PasswordChangeForm
    success_url = reverse_lazy('profile')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        user = form.save()
        update_session_auth_hash(self.request, user)
        messages.success(self.request, '密碼已更新。')
        return super().form_valid(form)


class AdminProfileUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = User
    form_class = AdminProfileForm
    template_name = 'accounts/admin_profile_form.html'
    success_url = reverse_lazy('profile')

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, '個人資料已更新。')
        response = super().form_valid(form)
        if form.cleaned_data.get('password'):
            update_session_auth_hash(self.request, self.object)
        return response


class TransferWindowSettingsView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'accounts/transfer_window_form.html'

    def get_archive_context(self, transfer_window):
        if not transfer_window:
            return {
                'transfer_record_archive_can_create': False,
                'transfer_record_archive_existing': None,
                'transfer_record_archive_request_count': 0,
            }

        today = timezone.localdate()
        can_create = transfer_window.is_paused or today > transfer_window.end_date
        existing = TransferRecordArchive.objects.filter(
            transfer_window=transfer_window,
            start_date=transfer_window.start_date,
            end_date=transfer_window.end_date,
        ).first()
        request_count = TransferRequest.objects.filter(
            created_at__date__gte=transfer_window.start_date,
            created_at__date__lte=transfer_window.end_date,
        ).count()
        return {
            'transfer_record_archive_can_create': can_create,
            'transfer_record_archive_existing': existing,
            'transfer_record_archive_request_count': request_count,
        }

    def get(self, request):
        state = get_transfer_window_state()
        form = TransferWindowForm(instance=state['transfer_window'])
        return render(
            request,
            self.template_name,
            {
                **state,
                **self.get_archive_context(state['transfer_window']),
                'form': form,
            },
        )

    def post(self, request):
        state = get_transfer_window_state()
        form = TransferWindowForm(request.POST, instance=state['transfer_window'])
        if form.is_valid():
            form.save()
            messages.success(request, '轉社期限設定已更新。')
            return redirect('transfer_window_settings')

        return render(
            request,
            self.template_name,
            {
                **state,
                **self.get_archive_context(state['transfer_window']),
                'form': form,
            },
        )


class TransferWindowPauseView(LoginRequiredMixin, AdminRequiredMixin, View):
    is_paused = True
    success_message = '轉社期已暫停。'

    def post(self, request):
        transfer_window = TransferWindow.get_current()
        if not transfer_window:
            messages.error(request, '尚未設定轉社期間。')
            return redirect('transfer_window_settings')

        transfer_window.is_paused = self.is_paused
        transfer_window.save(update_fields=['is_paused', 'updated_at'])
        messages.success(request, self.success_message)
        return redirect('transfer_window_settings')


class TransferWindowResumeView(TransferWindowPauseView):
    is_paused = False
    success_message = '轉社期已恢復。'


def build_approval_summary(transfer_request):
    logs = list(transfer_request.approval_logs.all().order_by('created_at'))
    if not logs:
        return '尚無審核紀錄'

    stage_labels = dict(TransferRequest.STATUS_CHOICES)
    result_labels = dict(ApprovalLog.RESULT_CHOICES)
    lines = []
    for log in logs:
        approver_name = (
            log.approver.get_full_name()
            or log.approver.first_name
            or log.approver.username
        )
        created_at = timezone.localtime(log.created_at).strftime('%Y/%m/%d %H:%M')
        stage = stage_labels.get(log.approval_stage, log.approval_stage)
        result = result_labels.get(log.result, log.result)
        comment = log.comment or '無意見'
        lines.append(f'{created_at}｜{stage}｜{approver_name}｜{result}｜{comment}')

    return '\n'.join(lines)


class TransferRecordArchiveCreateView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request):
        transfer_window = TransferWindow.get_current()
        if not transfer_window:
            messages.error(request, '尚未設定轉社期間。')
            return redirect('transfer_window_settings')

        today = timezone.localdate()
        if not (transfer_window.is_paused or today > transfer_window.end_date):
            messages.error(request, '只有轉社期已暫停或已截止後，才能儲存轉社記錄。')
            return redirect('transfer_window_settings')

        existing = TransferRecordArchive.objects.filter(
            transfer_window=transfer_window,
            start_date=transfer_window.start_date,
            end_date=transfer_window.end_date,
        ).first()
        if existing:
            messages.warning(request, '此轉社期已儲存。')
            return redirect('transfer_record_archive_detail', pk=existing.pk)

        transfer_requests = list(
            TransferRequest.objects.filter(
                created_at__date__gte=transfer_window.start_date,
                created_at__date__lte=transfer_window.end_date,
            )
            .select_related('student', 'original_club', 'target_club')
            .prefetch_related('approval_logs__approver')
            .order_by('created_at', 'pk')
        )

        with transaction.atomic():
            archive = TransferRecordArchive.objects.create(
                transfer_window=transfer_window,
                title=f'{transfer_window.start_date:%Y/%m/%d} ~ {transfer_window.end_date:%Y/%m/%d} 轉社紀錄',
                start_date=transfer_window.start_date,
                end_date=transfer_window.end_date,
                created_by=request.user,
            )
            snapshots = []
            for transfer_request in transfer_requests:
                student = transfer_request.student
                student_name = (
                    student.get_full_name()
                    or student.first_name
                    or student.username
                )
                snapshots.append(
                    TransferRecordSnapshot(
                        archive=archive,
                        student_name=student_name,
                        student_username=student.username,
                        student_id=student.student_id,
                        original_club_name=transfer_request.original_club.name,
                        target_club_name=transfer_request.target_club.name,
                        status=transfer_request.get_status_display(),
                        submitted_at=transfer_request.created_at,
                        approved_at=transfer_request.completed_at or transfer_request.updated_at,
                        approval_summary=build_approval_summary(transfer_request),
                    )
                )

            TransferRecordSnapshot.objects.bulk_create(snapshots)

        messages.success(request, f'已儲存 {len(snapshots)} 筆轉社紀錄。')
        return redirect('transfer_record_archive_detail', pk=archive.pk)


class TransferRecordArchiveListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = TransferRecordArchive
    template_name = 'accounts/transfer_record_archive_list.html'
    context_object_name = 'archives'
    paginate_by = 50

    def get_queryset(self):
        return TransferRecordArchive.objects.annotate(
            snapshot_count=Count('snapshots'),
        ).select_related('created_by').order_by('-archived_at')


class TransferRecordArchiveDetailView(LoginRequiredMixin, AdminRequiredMixin, DetailView):
    model = TransferRecordArchive
    template_name = 'accounts/transfer_record_archive_detail.html'
    context_object_name = 'archive'

    def get_queryset(self):
        return TransferRecordArchive.objects.select_related('created_by')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['snapshots'] = self.object.snapshots.all()
        return context


class AccountAdminListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    template_name = 'accounts/account_admin_list.html'
    context_object_name = 'accounts'
    paginate_by = 50

    allowed_roles = ['student', 'president', 'teacher']

    def get_queryset(self):
        queryset = User.objects.filter(
            role__in=self.allowed_roles,
            is_superuser=False,
        ).select_related('club').order_by('role', 'username')

        role = self.request.GET.get('role', '').strip()
        if role in self.allowed_roles:
            queryset = queryset.filter(role=role)
        elif role == 'inactive':
            queryset = queryset.filter(is_active=False)

        query = self.request.GET.get('q', '').strip()
        if query:
            queryset = queryset.filter(
                Q(username__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(student_id__icontains=query)
                | Q(email__icontains=query)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '').strip()
        context['selected_role'] = self.request.GET.get('role', '').strip()
        non_admin_accounts = User.objects.filter(is_superuser=False).exclude(role='admin')
        active_non_admin_accounts = non_admin_accounts.filter(is_active=True)
        context['account_stats'] = {
            'president_count': active_non_admin_accounts.filter(role='president').count(),
            'student_count': active_non_admin_accounts.filter(role='student').count(),
            'teacher_count': active_non_admin_accounts.filter(role='teacher').count(),
            'inactive_count': non_admin_accounts.filter(is_active=False).count(),
        }
        account_search_options = []
        for account in non_admin_accounts.filter(role__in=self.allowed_roles).order_by('first_name', 'email', 'student_id'):
            for value in (account.first_name, account.last_name, account.email, account.student_id):
                value = (value or '').strip()
                if value and value not in account_search_options:
                    account_search_options.append(value)
        context['account_search_options'] = account_search_options
        context['role_options'] = [
            ('', '全部'),
            ('student', '學生'),
            ('president', '社長'),
            ('teacher', '指導老師'),
            ('inactive', '已停用帳號'),
        ]
        return context


class AccountAdminBulkMixin:
    allowed_roles = ['student', 'president', 'teacher']

    def get_selected_accounts(self, request):
        account_ids = request.POST.getlist('account_ids')
        return User.objects.filter(
            pk__in=account_ids,
            role__in=self.allowed_roles,
            is_superuser=False,
        ).select_related('club').order_by('role', 'username')


class AccountAdminBulkReactivateView(
    LoginRequiredMixin,
    AdminRequiredMixin,
    AccountAdminBulkMixin,
    View,
):
    def post(self, request):
        accounts = list(self.get_selected_accounts(request))
        if not accounts:
            messages.warning(request, '請先選取要重新啟用的帳號。')
            return redirect('account_admin_list')

        with transaction.atomic():
            updated_count = 0
            for account in accounts:
                if not account.is_active:
                    account.is_active = True
                    account.save(update_fields=['is_active'])
                    updated_count += 1
            recalculate_club_current_members()

        messages.success(request, f'已批次重新啟用 {updated_count} 個帳號。')
        return redirect('account_admin_list')


class AccountAdminBulkDeactivateView(
    LoginRequiredMixin,
    AdminRequiredMixin,
    AccountAdminBulkMixin,
    View,
):
    def post(self, request):
        accounts = list(self.get_selected_accounts(request))
        if not accounts:
            messages.warning(request, '請先選取要停用的帳號。')
            return redirect('account_admin_list')

        with transaction.atomic():
            updated_count = 0
            protected_president_count = 0
            active_transfer_count = 0
            for account in accounts:
                if account.role in ['student', 'president']:
                    result = deactivate_student(account)
                    if result == 'president_requires_replacement':
                        protected_president_count += 1
                        continue
                    if result == 'active_transfer_requires_resolution':
                        active_transfer_count += 1
                        continue
                elif account.role == 'teacher':
                    deactivate_teacher(account)
                else:
                    continue
                updated_count += 1
            recalculate_club_current_members()

        message_level = messages.warning if protected_president_count or active_transfer_count else messages.success
        message_level(
            request,
            f'已批次停用 {updated_count} 個帳號；'
            f'{protected_president_count} 位啟用中社團的社長須先完成交接；'
            f'{active_transfer_count} 位學生須先結束進行中的轉社申請。',
        )
        return redirect('account_admin_list')


class AccountAdminBulkDeleteConfirmView(
    LoginRequiredMixin,
    AdminRequiredMixin,
    AccountAdminBulkMixin,
    View,
):
    template_name = 'accounts/account_admin_bulk_confirm_delete.html'

    def post(self, request):
        accounts = list(self.get_selected_accounts(request))
        if not accounts:
            messages.warning(request, '請先選取要刪除的帳號。')
            return redirect('account_admin_list')

        return render(request, self.template_name, {'accounts': accounts})


class AccountAdminBulkDeleteView(
    LoginRequiredMixin,
    AdminRequiredMixin,
    AccountAdminBulkMixin,
    View,
):
    def post(self, request):
        accounts = list(self.get_selected_accounts(request))
        deleted_count = 0
        deactivated_count = 0
        protected_president_count = 0
        active_transfer_count = 0

        with transaction.atomic():
            for account in accounts:
                if account.role in ['student', 'president']:
                    result = safely_delete_student(account)
                elif account.role == 'teacher':
                    result = safely_delete_teacher(account)
                else:
                    continue

                if result == 'deleted':
                    deleted_count += 1
                elif result == 'president_requires_replacement':
                    protected_president_count += 1
                elif result == 'active_transfer_requires_resolution':
                    active_transfer_count += 1
                else:
                    deactivated_count += 1

            recalculate_club_current_members()

        message_level = messages.warning if protected_president_count or active_transfer_count else messages.success
        message_level(
            request,
            f'批次刪除完成：刪除 {deleted_count} 個帳號，'
            f'因有歷史紀錄而停用 {deactivated_count} 個帳號；'
            f'{protected_president_count} 位啟用中社團的社長須先完成社長交接；'
            f'{active_transfer_count} 位學生須先結束進行中的轉社申請。',
        )
        return redirect('account_admin_list')


class AccountAdminCreateView(LoginRequiredMixin, AdminRequiredMixin, FormView):
    template_name = 'accounts/account_admin_form.html'
    form_class = AccountCreateForm
    success_url = reverse_lazy('account_admin_list')

    def form_valid(self, form):
        with transaction.atomic():
            club = form.cleaned_data.get('club')
            if form.cleaned_data['role'] == 'student' and club:
                club = Club.objects.select_for_update().get(pk=club.pk, is_active=True)
                if club.get_actual_member_count() >= club.max_members:
                    form.add_error('club', '此社團人數已滿。')
                    return self.form_invalid(form)
                form.cleaned_data['club'] = club
            user = form.save()
            recalculate_club_current_members()
        messages.success(self.request, f'已新增帳號 {user.username}。')
        return super().form_valid(form)


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
                Q(student_id__icontains=query)
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


def create_assignment_log(operator, student, club):
    """Persist unassigned-account assignments without adding a project model."""
    change_message = {
        'type': ASSIGNMENT_LOG_MARKER,
        'student_id': student.pk,
        'student_name': student.get_full_name() or student.first_name or student.username,
        'original_club': '未分配',
        'target_club_id': club.pk,
        'target_club_name': club.name,
        'operation_type': '分配',
    }
    LogEntry.objects.create(
        user_id=operator.pk,
        content_type=ContentType.objects.get_for_model(User),
        object_id=str(student.pk),
        object_repr=str(student)[:200],
        action_flag=CHANGE,
        change_message=json.dumps(change_message, ensure_ascii=False),
    )


def parse_assignment_log(log_entry):
    try:
        message = json.loads(log_entry.change_message or '{}')
    except json.JSONDecodeError:
        return None

    if message.get('type') != ASSIGNMENT_LOG_MARKER:
        return None

    return {
        'student_name': message.get('student_name') or log_entry.object_repr,
        'original_club_name': message.get('original_club') or '未分配',
        'target_club_name': message.get('target_club_name') or '-',
        'operation_type': message.get('operation_type') or '分配',
        'operated_at': log_entry.action_time,
        'operator': log_entry.user,
        'source': None,
    }


class AssignmentRecordListView(LoginRequiredMixin, AdminRequiredMixin, TemplateView):
    template_name = 'accounts/assignment_record_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        transfer_requests = TransferRequest.objects.filter(
            status='approved',
        ).select_related(
            'student',
            'original_club',
            'target_club',
        ).order_by('-completed_at', '-updated_at', '-created_at')

        records = []
        for transfer_request in transfer_requests:
            latest_log = transfer_request.approval_logs.select_related('approver').order_by('-created_at').first()
            records.append({
                'student_name': transfer_request.student.get_full_name() or transfer_request.student.username,
                'original_club_name': transfer_request.original_club.name,
                'target_club_name': transfer_request.target_club.name,
                'operation_type': '轉社',
                'operated_at': (
                    transfer_request.completed_at
                    or transfer_request.updated_at
                    or transfer_request.created_at
                ),
                'operator': latest_log.approver if latest_log else None,
                'source': transfer_request,
            })

        user_content_type = ContentType.objects.get_for_model(User)
        assignment_logs = LogEntry.objects.filter(
            content_type=user_content_type,
            action_flag=CHANGE,
            change_message__contains=ASSIGNMENT_LOG_MARKER,
        ).select_related('user').order_by('-action_time')

        for log_entry in assignment_logs:
            record = parse_assignment_log(log_entry)
            if record:
                records.append(record)

        records.sort(key=lambda record: record['operated_at'], reverse=True)
        context['records'] = records
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
            student = get_object_or_404(
                User.objects.select_for_update(),
                pk=student.pk,
                role='student',
                is_active=True,
                club__isnull=True,
            )
            club = Club.objects.select_for_update().get(pk=club.pk, is_active=True)
            if club.get_actual_member_count() >= club.max_members:
                messages.warning(request, f'{club.name} 人數已滿，無法分配。')
                return redirect('unassigned_account_list')

            student.club = club
            student.save(update_fields=['club'])
            create_assignment_log(request.user, student, club)
            recalculate_club_current_members()

        student_name = student.get_full_name() or student.first_name or student.username
        messages.success(request, f'已將 {student_name} 分配至 {club.name}，並更新分配紀錄。')
        return redirect('unassigned_account_list')


class UnassignedStudentBulkAssignClubView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request):
        student_ids = request.POST.getlist('student_ids')
        club_id = request.POST.get('club_id')

        if not student_ids:
            messages.error(request, '請先選取學生。')
            return redirect('unassigned_account_list')

        if not club_id:
            messages.error(request, '請先選擇社團。')
            return redirect('unassigned_account_list')

        with transaction.atomic():
            club = get_object_or_404(Club.objects.select_for_update(), pk=club_id, is_active=True)
            unique_student_ids = set(student_ids)
            students = list(
                User.objects.select_for_update().filter(
                    pk__in=unique_student_ids,
                    role='student',
                    is_active=True,
                    club__isnull=True,
                )
            )

            if len(students) != len(unique_student_ids):
                messages.error(request, '選取的帳號包含非學生、已分配或已停用帳號，無法分配。')
                return redirect('unassigned_account_list')

            if club.get_actual_member_count() + len(students) > club.max_members:
                messages.warning(request, f'{club.name} 人數已滿，無法分配。')
                return redirect('unassigned_account_list')

            User.objects.filter(pk__in=[student.pk for student in students]).update(club=club)
            for student in students:
                student.club = club
                create_assignment_log(request.user, student, club)
            recalculate_club_current_members()

        messages.success(request, f'已將 {len(students)} 位學生分配至 {club.name}，並更新分配紀錄。')
        return redirect('unassigned_account_list')


class TeacherAdminListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = User
    template_name = 'accounts/teacher_admin_list.html'
    context_object_name = 'teachers'
    paginate_by = 50

    def get_queryset(self):
        queryset = User.objects.filter(role='teacher').order_by('username')
        query = self.request.GET.get('q', '').strip()
        if query:
            queryset = queryset.filter(
                Q(username__icontains=query)
                | Q(first_name__icontains=query)
                | Q(email__icontains=query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        teachers = list(context['teachers'])
        for teacher in teachers:
            teacher.guided_clubs = self.get_guided_clubs(teacher)
        context['teachers'] = teachers
        context['q'] = self.request.GET.get('q', '').strip()
        return context

    def get_guided_clubs(self, teacher):
        return Club.objects.filter(
            teacher__icontains=f'({teacher.username})',
            is_active=True,
        ).order_by('code', 'name')


class TeacherAdminCreateView(LoginRequiredMixin, AdminRequiredMixin, AccountAdminReturnMixin, CreateView):
    model = User
    form_class = TeacherAccountForm
    template_name = 'accounts/teacher_admin_form.html'
    success_url = reverse_lazy('teacher_admin_list')
    default_success_url_name = 'teacher_admin_list'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['is_create'] = True
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, '指導老師帳號已新增。')
        return super().form_valid(form)


class TeacherAdminUpdateView(LoginRequiredMixin, AdminRequiredMixin, AccountAdminReturnMixin, UpdateView):
    model = User
    form_class = TeacherAccountForm
    template_name = 'accounts/teacher_admin_form.html'
    success_url = reverse_lazy('teacher_admin_list')
    default_success_url_name = 'teacher_admin_list'

    def get_queryset(self):
        return User.objects.filter(role='teacher')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['is_create'] = False
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            original = User.objects.select_for_update().get(pk=self.object.pk)
            referenced_club_ids = []
            for club in Club.objects.select_for_update().exclude(teacher=''):
                referenced_teacher = get_user_from_display_text(club.teacher)
                if referenced_teacher and referenced_teacher.pk == original.pk:
                    referenced_club_ids.append(club.pk)

            response = super().form_valid(form)
            if self.object.is_active:
                Club.objects.filter(pk__in=referenced_club_ids).update(
                    teacher=format_club_user_display_text(self.object)
                )
            else:
                Club.objects.filter(pk__in=referenced_club_ids).update(teacher='')
        messages.success(self.request, '指導老師資料已更新。')
        return response


class TeacherAdminDeactivateView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'accounts/teacher_admin_confirm_deactivate.html'

    def get(self, request, pk):
        teacher = get_object_or_404(User, pk=pk, role='teacher')
        return render(
            request,
            self.template_name,
            {
                'teacher': teacher,
                'return_to_account_admin': should_return_to_account_admin(request),
            },
        )

    def post(self, request, pk):
        teacher = get_object_or_404(User, pk=pk, role='teacher')
        with transaction.atomic():
            deactivate_teacher(teacher)
        messages.success(request, '指導老師帳號已停用。')
        return redirect(admin_operation_return_url(request, 'teacher_admin_list'))


class TeacherAdminReactivateView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk):
        teacher = get_object_or_404(User, pk=pk, role='teacher')
        teacher.is_active = True
        teacher.save(update_fields=['is_active'])
        messages.success(request, '指導老師帳號已重新啟用。')
        return redirect(admin_operation_return_url(request, 'teacher_admin_list'))


class TeacherAdminDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'accounts/teacher_admin_confirm_delete.html'

    def get(self, request, pk):
        teacher = get_object_or_404(User, pk=pk, role='teacher')
        return render(
            request,
            self.template_name,
            {
                'teacher': teacher,
                'return_to_account_admin': should_return_to_account_admin(request),
            },
        )

    def post(self, request, pk):
        teacher = get_object_or_404(User, pk=pk, role='teacher')

        with transaction.atomic():
            result = safely_delete_teacher(teacher)
            if result == 'deactivated':
                messages.warning(
                    request,
                    '此指導老師已有審核紀錄，為保留歷史資料，系統已改為停用而非刪除。',
                )
            else:
                messages.success(request, '指導老師帳號已刪除。')

        return redirect(admin_operation_return_url(request, 'teacher_admin_list'))


class ClubAdminListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = Club
    template_name = 'accounts/club_admin_list.html'
    context_object_name = 'clubs'
    paginate_by = 50

    def get_queryset(self):
        queryset = Club.objects.annotate(
            actual_member_count=Count(
                'members',
                filter=Q(
                    members__role__in=['student', 'president'],
                    members__is_active=True,
                ),
            )
        ).order_by('-is_active', 'code', 'name')
        query = self.request.GET.get('q', '').strip()
        if query:
            queryset = queryset.filter(name__icontains=query)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '').strip()
        context['club_name_options'] = Club.objects.order_by('name').values_list('name', flat=True)
        return context


class ClubAdminBulkMixin:
    def get_selected_clubs(self, request):
        club_ids = request.POST.getlist('club_ids')
        return Club.objects.filter(pk__in=club_ids).order_by('code', 'name')


class ClubAdminDeactivateView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk):
        with transaction.atomic():
            club = get_object_or_404(Club.objects.select_for_update(), pk=pk)
            deactivate_club(club)
            recalculate_club_current_members()

        messages.success(request, f'已停用 {club.name}，並將成員移至未分配帳號。')
        return redirect('club_admin_list')


class ClubAdminReactivateView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk):
        with transaction.atomic():
            club = get_object_or_404(Club.objects.select_for_update(), pk=pk)
            if not reactivate_club(club):
                messages.error(request, '請先編輯社團並指派有效社長與指導老師，再重新啟用。')
                return redirect('club_admin_list')
            recalculate_club_current_members()

        messages.success(request, f'已重新啟用 {club.name}。')
        return redirect('club_admin_list')


class ClubAdminBulkDeactivateView(
    LoginRequiredMixin,
    AdminRequiredMixin,
    ClubAdminBulkMixin,
    View,
):
    def post(self, request):
        with transaction.atomic():
            clubs = list(self.get_selected_clubs(request).select_for_update())
            if not clubs:
                messages.error(request, '請先選取社團。')
                return redirect('club_admin_list')
            for club in clubs:
                deactivate_club(club)
            recalculate_club_current_members()

        messages.success(request, f'已批次停用 {len(clubs)} 個社團。')
        return redirect('club_admin_list')


class ClubAdminBulkReactivateView(
    LoginRequiredMixin,
    AdminRequiredMixin,
    ClubAdminBulkMixin,
    View,
):
    def post(self, request):
        with transaction.atomic():
            clubs = list(self.get_selected_clubs(request).select_for_update())
            if not clubs:
                messages.error(request, '請先選取社團。')
                return redirect('club_admin_list')
            reactivated_count = 0
            skipped_count = 0
            for club in clubs:
                if reactivate_club(club):
                    reactivated_count += 1
                else:
                    skipped_count += 1
            recalculate_club_current_members()

        message_level = messages.warning if skipped_count else messages.success
        message_level(
            request,
            f'已批次重新啟用 {reactivated_count} 個社團；'
            f'{skipped_count} 個社團因缺少有效社長或指導老師而略過。',
        )
        return redirect('club_admin_list')


class ClubAdminBulkDeleteView(
    LoginRequiredMixin,
    AdminRequiredMixin,
    ClubAdminBulkMixin,
    View,
):
    def post(self, request):
        with transaction.atomic():
            clubs = list(self.get_selected_clubs(request).select_for_update())
            if not clubs:
                messages.error(request, '請先選取社團。')
                return redirect('club_admin_list')
            deleted_count = 0
            deactivated_count = 0
            for club in clubs:
                result = safely_delete_club(club)
                if result == 'deleted':
                    deleted_count += 1
                else:
                    deactivated_count += 1
            recalculate_club_current_members()

        messages.warning(
            request,
            f'批次刪除完成：刪除 {deleted_count} 個社團；'
            f'因有轉社歷史而停用 {deactivated_count} 個社團。',
        )
        return redirect('club_admin_list')


class ClubAdminCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = Club
    form_class = ClubAdminForm
    template_name = 'accounts/club_admin_form.html'
    success_url = reverse_lazy('club_admin_list')

    def form_valid(self, form):
        with transaction.atomic():
            president = User.objects.select_for_update().filter(
                pk=form.selected_president.pk,
                role='student',
                is_active=True,
                club__isnull=True,
            ).first()
            if not president:
                form.add_error('president', '此學生已無法擔任新社團社長，請重新選擇。')
                return self.form_invalid(form)
            self.object = form.save()
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        members = list(
            User.objects.filter(
                club=self.object,
                role__in=['student', 'president'],
                is_active=True,
            ).order_by('role', 'username')
        )
        club_members = [
            {
                'user': member,
                'is_president': is_club_president_user(member, self.object),
            }
            for member in members
        ]
        context['club_members'] = sorted(
            club_members,
            key=lambda member_info: (
                0 if member_info['is_president'] else 1,
                member_info['user'].first_name or member_info['user'].username,
            ),
        )
        return context

    def form_valid(self, form):
        previous_president_text = Club.objects.only('president').get(pk=self.object.pk).president
        previous_president = get_user_from_display_text(previous_president_text)
        previous_president_ids = list(
            User.objects.filter(club=self.object, role='president').values_list('pk', flat=True)
        )
        if previous_president and previous_president.role == 'president':
            previous_president_ids.append(previous_president.pk)

        with transaction.atomic():
            locked_club = Club.objects.select_for_update().get(pk=self.object.pk)
            new_president = User.objects.select_for_update().filter(
                pk=form.selected_president.pk,
                is_active=True,
            ).first()
            valid_current_president = bool(
                new_president
                and new_president.role == 'president'
                and new_president.club_id == locked_club.pk
            )
            valid_unassigned_student = bool(
                new_president
                and new_president.role == 'student'
                and new_president.club_id is None
            )
            if not valid_current_president and not valid_unassigned_student:
                form.add_error('president', '此學生的狀態已變更，請重新選擇社長。')
                return self.form_invalid(form)
            added_president_count = int(new_president.club_id != locked_club.pk)
            if (
                locked_club.get_actual_member_count() + added_president_count
                > form.cleaned_data['max_members']
            ):
                form.add_error('max_members', '人數上限不可低於更新後的實際社員人數。')
                return self.form_invalid(form)

            self.object = form.save()

            User.objects.filter(
                pk__in=previous_president_ids,
            ).exclude(pk=new_president.pk).update(role='student', club=self.object)
            demote_other_club_presidents(self.object, new_president)

            new_president.role = 'president'
            new_president.club = self.object
            new_president.save(update_fields=['role', 'club'])
            recalculate_club_current_members()

        messages.success(self.request, '社團資料已更新。')
        return redirect(self.get_success_url())


class ClubAdminMemberUnassignView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, club_pk, user_pk):
        with transaction.atomic():
            club = get_object_or_404(Club.objects.select_for_update(), pk=club_pk)
            member = get_object_or_404(
                User.objects.select_for_update(),
                pk=user_pk,
                club=club,
                role__in=['student', 'president'],
            )

            if is_club_president_user(member, club):
                remaining_members = User.objects.filter(
                    club=club,
                    role__in=['student', 'president'],
                    is_active=True,
                ).exclude(pk=member.pk)

                if not remaining_members.exists():
                    messages.error(request, '社團至少需要一位社長，請先加入其他成員後再移除')
                    return redirect('club_admin_edit', pk=club.pk)

                return redirect(
                    'club_admin_replace_president',
                    club_pk=club.pk,
                    user_pk=member.pk,
                )

            member.club = None
            update_fields = ['club']
            if member.role == 'president':
                member.role = 'student'
                update_fields.append('role')
            member.save(update_fields=update_fields)
            recalculate_club_current_members()

        messages.success(request, f'已將 {member.username} 移至未分配帳號。')
        return redirect('club_admin_edit', pk=club_pk)


class ClubAdminReplacePresidentView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'accounts/club_admin_replace_president.html'

    def get_candidates(self, club, old_president):
        return User.objects.filter(
            club=club,
            role__in=['student', 'president'],
            is_active=True,
        ).exclude(pk=old_president.pk).order_by('username')

    def get(self, request, club_pk, user_pk):
        club = get_object_or_404(Club, pk=club_pk)
        old_president = get_object_or_404(
            User,
            pk=user_pk,
            club=club,
            role__in=['student', 'president'],
        )

        if not is_club_president_user(old_president, club):
            messages.error(request, '該成員不是目前社長。')
            return redirect('club_admin_edit', pk=club.pk)

        candidates = self.get_candidates(club, old_president)
        if not candidates.exists():
            messages.error(request, '社團至少需要一位社長，請先加入其他成員後再移除')
            return redirect('club_admin_edit', pk=club.pk)

        return render(
            request,
            self.template_name,
            {
                'club': club,
                'old_president': old_president,
                'candidates': candidates,
            },
        )

    def post(self, request, club_pk, user_pk):
        new_president_id = request.POST.get('new_president_id')
        if not new_president_id:
            messages.error(request, '請選擇新社長。')
            return redirect('club_admin_replace_president', club_pk=club_pk, user_pk=user_pk)

        with transaction.atomic():
            club = get_object_or_404(Club.objects.select_for_update(), pk=club_pk)
            old_president = get_object_or_404(
                User.objects.select_for_update(),
                pk=user_pk,
                club=club,
                role__in=['student', 'president'],
            )

            if not is_club_president_user(old_president, club):
                messages.error(request, '該成員不是目前社長。')
                return redirect('club_admin_edit', pk=club.pk)

            candidates = self.get_candidates(club, old_president)
            new_president = get_object_or_404(
                candidates.select_for_update(),
                pk=new_president_id,
            )

            User.objects.filter(
                club=club,
                role='president',
            ).exclude(pk=new_president.pk).update(role='student')
            demote_other_club_presidents(club, new_president)

            old_president.role = 'student'
            old_president.club = None
            old_president.save(update_fields=['role', 'club'])

            new_president.role = 'president'
            new_president.club = club
            new_president.save(update_fields=['role', 'club'])

            club.president = format_club_user_display_text(new_president)
            club.save(update_fields=['president'])
            recalculate_club_current_members()

        messages.success(request, f'已改由 {new_president.username} 擔任社長，並將原社長移至未分配帳號。')
        return redirect('club_admin_edit', pk=club_pk)


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
            released_count = User.objects.filter(club=club).count()
            result = safely_delete_club(club)
            recalculate_club_current_members()

        if result == 'deactivated':
            messages.warning(
                request,
                f'社團有轉社歷史，已改為停用並解除 {released_count} 位成員的社團分配。',
            )
        else:
            messages.success(
                request,
                f'社團已刪除，並解除 {released_count} 位成員的社團分配。',
            )
        return redirect('club_admin_list')

    def get_active_members(self, club):
        return User.objects.filter(
            club=club,
            is_active=True,
            role__in=['student', 'president'],
        ).order_by('role', 'username')


class ClubCsvImportView(LoginRequiredMixin, AdminRequiredMixin, FormView):
    template_name = 'accounts/club_admin_import.html'
    form_class = ClubCsvImportForm
    success_url = reverse_lazy('club_admin_import')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sample_csv'] = SAMPLE_CLUB_IMPORT_CSV
        context['result'] = getattr(self, 'result', None)
        return context

    def form_valid(self, form):
        self.result = import_clubs_from_csv(form.cleaned_data['csv_file'])
        return self.render_to_response(self.get_context_data(form=form))


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
                | Q(email__icontains=query)
                | Q(student_id__icontains=query)
                | Q(first_name__icontains=query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '').strip()
        return context


class StudentAdminCreateView(LoginRequiredMixin, AdminRequiredMixin, AccountAdminReturnMixin, CreateView):
    model = User
    form_class = StudentAccountForm
    template_name = 'accounts/student_admin_form.html'
    success_url = reverse_lazy('student_admin_list')
    default_success_url_name = 'student_admin_list'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['is_create'] = True
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            club = form.cleaned_data.get('club')
            if club:
                club = Club.objects.select_for_update().get(pk=club.pk, is_active=True)
                if club.get_actual_member_count() >= club.max_members:
                    form.add_error('club', '此社團人數已滿。')
                    return self.form_invalid(form)
                form.instance.club = club
            response = super().form_valid(form)
            recalculate_club_current_members()
        messages.success(self.request, '學生帳號已新增。')
        return response


class StudentAdminUpdateView(LoginRequiredMixin, AdminRequiredMixin, AccountAdminReturnMixin, UpdateView):
    model = User
    form_class = StudentAccountForm
    template_name = 'accounts/student_admin_form.html'
    success_url = reverse_lazy('student_admin_list')
    default_success_url_name = 'student_admin_list'

    def get_queryset(self):
        return User.objects.filter(role__in=['student', 'president'])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['is_create'] = False
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            original = User.objects.select_for_update().select_related('club').get(pk=self.object.pk)
            was_assigned_president = bool(
                original.club_id
                and original.role == 'president'
                and is_club_president_user(original, original.club)
            )
            original_club_id = original.club_id
            target_club = form.cleaned_data.get('club')
            if target_club:
                target_club = Club.objects.select_for_update().get(
                    pk=target_club.pk,
                    is_active=True,
                )
                if target_club.get_actual_member_count(exclude_user_id=original.pk) >= target_club.max_members:
                    form.add_error('club', '此社團人數已滿。')
                    return self.form_invalid(form)
                form.instance.club = target_club
            response = super().form_valid(form)
            if self.object.role == 'president':
                if was_assigned_president and self.object.club_id == original_club_id:
                    self.object.club.president = format_club_user_display_text(self.object)
                    self.object.club.save(update_fields=['president'])
                current_president = (
                    get_user_from_display_text(self.object.club.president)
                    if self.object.club_id and self.object.club.president
                    else None
                )
                if not current_president or current_president.pk != self.object.pk:
                    clear_president_assignment(self.object)
                    self.object.role = 'student'
                    self.object.save(update_fields=['role'])
            recalculate_club_current_members()

        messages.success(self.request, '學生資料已更新。')
        return response


class StudentAdminDeactivateView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'accounts/student_admin_confirm_deactivate.html'

    def get(self, request, pk):
        student = get_object_or_404(User, pk=pk, role__in=['student', 'president'])
        return render(
            request,
            self.template_name,
            {
                'student': student,
                'return_to_account_admin': should_return_to_account_admin(request),
            },
        )

    def post(self, request, pk):
        with transaction.atomic():
            student = get_object_or_404(
                User.objects.select_for_update(),
                pk=pk,
                role__in=['student', 'president'],
            )
            result = deactivate_student(student)
            recalculate_club_current_members()
        if result == 'president_requires_replacement':
            messages.error(request, '此帳號是啟用中社團的社長，請先完成社長交接。')
        elif result == 'active_transfer_requires_resolution':
            messages.error(request, '此學生有進行中的轉社申請，請先結束申請再停用帳號。')
        else:
            messages.success(request, '學生帳號已停用。')
        return redirect(admin_operation_return_url(request, 'student_admin_list'))


class StudentAdminReactivateView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk):
        student = get_object_or_404(User, pk=pk, role__in=['student', 'president'])
        student.is_active = True
        student.save(update_fields=['is_active'])
        recalculate_club_current_members()
        messages.success(request, '學生帳號已重新啟用。')
        return redirect(admin_operation_return_url(request, 'student_admin_list'))


class StudentAdminBulkMixin:
    def get_selected_students(self, request):
        student_ids = request.POST.getlist('student_ids')
        return User.objects.filter(
            pk__in=student_ids,
            role__in=['student', 'president'],
        ).order_by('username')


class StudentAdminBulkDeactivateView(
    LoginRequiredMixin,
    AdminRequiredMixin,
    StudentAdminBulkMixin,
    View,
):
    def post(self, request):
        students = list(self.get_selected_students(request))
        if not students:
            messages.warning(request, '請先選取要停用的學生。')
            return redirect('student_admin_list')
        with transaction.atomic():
            updated_count = 0
            protected_president_count = 0
            active_transfer_count = 0
            for student in students:
                result = deactivate_student(student)
                if result == 'president_requires_replacement':
                    protected_president_count += 1
                elif result == 'active_transfer_requires_resolution':
                    active_transfer_count += 1
                else:
                    updated_count += 1
            recalculate_club_current_members()

        message_level = messages.warning if protected_president_count or active_transfer_count else messages.success
        message_level(
            request,
            f'已批次停用 {updated_count} 位學生；'
            f'{protected_president_count} 位啟用中社團的社長須先完成交接；'
            f'{active_transfer_count} 位學生須先結束進行中的轉社申請。',
        )
        return redirect('student_admin_list')


class StudentAdminBulkReactivateView(
    LoginRequiredMixin,
    AdminRequiredMixin,
    StudentAdminBulkMixin,
    View,
):
    def post(self, request):
        students = self.get_selected_students(request)
        if not students.exists():
            messages.warning(request, '請先選取要重新啟用的學生。')
            return redirect('student_admin_list')
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
        protected_president_count = 0
        active_transfer_count = 0

        with transaction.atomic():
            for student in students:
                result = safely_delete_student(student)
                if result == 'deleted':
                    deleted_count += 1
                elif result == 'president_requires_replacement':
                    protected_president_count += 1
                elif result == 'active_transfer_requires_resolution':
                    active_transfer_count += 1
                else:
                    deactivated_count += 1
            recalculate_club_current_members()

        message_level = messages.warning if protected_president_count or active_transfer_count else messages.success
        message_level(
            request,
            f'批次刪除完成：刪除 {deleted_count} 位學生，'
            f'因有歷史紀錄而停用 {deactivated_count} 位學生；'
            f'{protected_president_count} 位啟用中社團的社長須先完成社長交接；'
            f'{active_transfer_count} 位學生須先結束進行中的轉社申請。',
        )
        return redirect('student_admin_list')


class StudentAdminDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'accounts/student_admin_confirm_delete.html'

    def get(self, request, pk):
        student = get_object_or_404(User, pk=pk, role__in=['student', 'president'])
        return render(
            request,
            self.template_name,
            {
                'student': student,
                'return_to_account_admin': should_return_to_account_admin(request),
            },
        )

    def post(self, request, pk):
        with transaction.atomic():
            student = get_object_or_404(
                User.objects.select_for_update(),
                pk=pk,
                role__in=['student', 'president'],
            )
            result = safely_delete_student(student)
            if result == 'president_requires_replacement':
                messages.error(
                    request,
                    '此帳號是啟用中社團的社長，請先在社團管理完成社長交接後再刪除。',
                )
            elif result == 'active_transfer_requires_resolution':
                messages.error(
                    request,
                    '此學生有進行中的轉社申請，請先結束申請再刪除帳號。',
                )
            elif result == 'deactivated':
                messages.warning(
                    request,
                    '此學生已有申請或審核紀錄，為保留歷史資料，系統已改為停用而非刪除。',
                )
            else:
                messages.success(request, '學生帳號已刪除。')

            recalculate_club_current_members()

        return redirect(admin_operation_return_url(request, 'student_admin_list'))

class StudentAdminPromotePresidentView(LoginRequiredMixin, AdminRequiredMixin, View):
    success_url_name = 'student_admin_list'

    def post(self, request, pk):
        student = get_object_or_404(User.objects.select_related('club'), pk=pk)

        if student.role == 'president':
            messages.warning(request, '此學生已經是社長，無法重複晉升。')
            return redirect(self.success_url_name)

        if student.role != 'student':
            messages.error(request, '只有一般學生可以晉升為社長。')
            return redirect(self.success_url_name)

        if not student.is_active:
            messages.error(request, '停用中的學生不能晉升為社長。')
            return redirect(self.success_url_name)

        if not student.club_id:
            messages.error(request, '此學生目前沒有社團，無法晉升為社長。')
            return redirect(self.success_url_name)

        if not student.club.is_active:
            messages.error(request, '停用中的社團不能指派社長。')
            return redirect(self.success_url_name)

        if TransferRequest.objects.filter(
            student=student,
            status__in=ACTIVE_TRANSFER_STATUSES,
        ).exists():
            messages.error(request, '此學生有進行中的轉社申請，完成或結束申請前不能晉升為社長。')
            return redirect(self.success_url_name)

        with transaction.atomic():
            student = User.objects.select_for_update().select_related('club').get(pk=student.pk)
            club = Club.objects.select_for_update().get(pk=student.club_id)
            if not student.is_active or student.role != 'student' or not club.is_active:
                messages.error(request, '學生或社團狀態已變更，無法晉升為社長。')
                return redirect(self.success_url_name)
            if TransferRequest.objects.select_for_update().filter(
                student=student,
                status__in=ACTIVE_TRANSFER_STATUSES,
            ).exists():
                messages.error(request, '此學生有進行中的轉社申請，無法晉升為社長。')
                return redirect(self.success_url_name)
            previous_president = get_user_from_display_text(club.president)
            missing_president_notice = False

            if previous_president and previous_president.pk != student.pk:
                previous_president = User.objects.select_for_update().get(pk=previous_president.pk)
                previous_president.role = 'student'
                previous_president.club = club
                previous_president.save(update_fields=['role', 'club'])
            elif club.president:
                missing_president_notice = True
            demote_other_club_presidents(club, student)

            student.role = 'president'
            student.club = club
            student.save(update_fields=['role', 'club'])

            display_name = student.get_full_name() or student.first_name or student.username
            club.president = f'{display_name} ({student.username})'
            club.save(update_fields=['president'])

            recalculate_club_current_members()

        if missing_president_notice:
            messages.warning(request, '原社長資料未完整，已直接更新社長欄位。')
        messages.success(request, f'已將 {display_name} 晉升為社長')
        return redirect(self.success_url_name)


class AccountAdminPromotePresidentView(StudentAdminPromotePresidentView):
    success_url_name = 'account_admin_list'


class StudentCsvImportView(LoginRequiredMixin, AdminRequiredMixin, FormView):
    template_name = 'accounts/student_admin_import.html'
    form_class = StudentCsvImportForm
    success_url = reverse_lazy('account_admin_import')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sample_csv'] = SAMPLE_STUDENT_IMPORT_CSV
        context['result'] = getattr(self, 'result', None)
        return context

    def form_valid(self, form):
        self.result = import_students_from_csv(form.cleaned_data['csv_file'])
        return self.render_to_response(self.get_context_data(form=form))
