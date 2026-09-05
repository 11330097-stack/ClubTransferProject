from django.views.generic import ListView, DetailView, CreateView, UpdateView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.contrib import messages
from django.db import IntegrityError, transaction, models
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from .models import TransferRequest, ApprovalLog
from .services import get_transfer_window_state
from clubs.models import Club
from accounts.models import User
from accounts.permissions import can_review_transfer_requests, is_training_admin


REVIEWABLE_STATUSES = [
    'orig_president_pending',
    'orig_teacher_pending',
    'new_president_pending',
    'new_teacher_pending',
    'admin_pending',
]
ACTIVE_REQUEST_STATUSES = REVIEWABLE_STATUSES + ['returned']


def get_transfer_state_error(transfer_request):
    student = transfer_request.student
    if not student.is_active or student.role != 'student':
        return '申請學生已停用或身分已變更，無法繼續審核。'
    if student.club_id != transfer_request.original_club_id:
        return '申請學生已不屬於原社團，無法繼續審核。'
    if transfer_request.original_club_id == transfer_request.target_club_id:
        return '原社團與目標社團不可相同。'
    if not transfer_request.original_club.is_active:
        return '原社團已停用，無法繼續審核。'
    if not transfer_request.target_club.is_active:
        return '目標社團已停用，無法繼續審核。'
    return None


def sync_member_counts(*clubs):
    for club in {club.pk: club for club in clubs}.values():
        club.current_members = club.get_actual_member_count()
        club.save(update_fields=['current_members'])


class StudentRequiredMixin(UserPassesTestMixin):
    """檢查是否為學生"""
    def test_func(self):
        return self.request.user.role in ['student', 'president']


class TransferApplicantRequiredMixin(UserPassesTestMixin):
    """檢查是否可送出轉社申請"""
    def test_func(self):
        return self.request.user.role == 'student'

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            role_messages = {
                'president': '社長目前不可申請轉社，請先完成社長交接',
                'teacher': '指導老師不可申請轉社',
                'admin': '訓育組不可申請轉社',
            }
            message = role_messages.get(self.request.user.role)
            if message:
                messages.error(self.request, message)
                return redirect('home')
        return super().handle_no_permission()


class ApproverRequiredMixin(UserPassesTestMixin):
    """檢查是否為審核者（社長、老師、管理員）"""
    def test_func(self):
        user = self.request.user
        return can_review_transfer_requests(user)


class AdminRequiredMixin(UserPassesTestMixin):
    """檢查是否為訓育組管理員"""
    def test_func(self):
        return is_training_admin(self.request.user)


class TransferWindowOpenRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        state = get_transfer_window_state()
        if not state['transfer_window_is_open']:
            if state['transfer_window_status'] == 'paused':
                messages.error(request, '轉社申請目前暫停')
            else:
                messages.error(request, '目前不在轉社申請期間內')
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)


class TransferApplyView(LoginRequiredMixin, TransferApplicantRequiredMixin, TransferWindowOpenRequiredMixin, CreateView):
    """
    提交轉社申請
    """
    model = TransferRequest
    template_name = 'transfers/transfer_form.html'
    fields = ['target_club', 'reason']
    success_url = reverse_lazy('my_requests')
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        user = self.request.user
        
        # 防錯機制：過濾掉原社團和已滿的社團
        available_clubs = Club.objects.filter(is_active=True).annotate(
            actual_members=models.Count(
                'members',
                filter=models.Q(
                    members__role__in=['student', 'president'],
                    members__is_active=True,
                ),
            )
        ).filter(actual_members__lt=models.F('max_members'))
        if user.club:
            available_clubs = available_clubs.exclude(id=user.club.id)
        
        form.fields['target_club'].queryset = available_clubs
        form.fields['target_club'].label = '目標社團'
        form.fields['target_club'].empty_label = '請選擇社團'
        form.fields['reason'].label = '轉社原因'
        form.fields['reason'].widget.attrs['rows'] = 4

        target_club_id = self.request.GET.get('target_club')
        if target_club_id and available_clubs.filter(pk=target_club_id).exists():
            form.initial['target_club'] = target_club_id
        
        return form
    
    def form_valid(self, form):
        try:
            with transaction.atomic():
                user = User.objects.select_for_update().select_related('club').get(
                    pk=self.request.user.pk
                )
                if not user.is_active or user.role != 'student':
                    messages.error(self.request, '目前帳號狀態無法提出轉社申請。')
                    return redirect('home')
                if not user.club_id:
                    messages.error(self.request, '您目前沒有所屬社團，無法申請轉社')
                    return redirect('transfer_apply')

                original_club = Club.objects.select_for_update().get(pk=user.club_id)
                target_club = Club.objects.select_for_update().filter(
                    pk=form.cleaned_data['target_club'].pk,
                    is_active=True,
                ).first()
                if not original_club.is_active:
                    messages.error(self.request, '原社團已停用，無法提出轉社申請。')
                    return redirect('my_requests')
                if not target_club or target_club.pk == original_club.pk:
                    messages.error(self.request, '目標社團無效或與原社團相同。')
                    return redirect('transfer_apply')
                if target_club.get_actual_member_count() >= target_club.max_members:
                    messages.error(self.request, '目標社團已額滿。')
                    return redirect('transfer_apply')

                existing = TransferRequest.objects.select_for_update().filter(
                    student=user,
                    status__in=ACTIVE_REQUEST_STATUSES,
                ).first()
                if existing:
                    messages.error(
                        self.request,
                        f'您已有進行中的轉社申請（{existing.get_status_display()}），請先完成或取消該申請',
                    )
                    return redirect('my_requests')

                form.instance.student = user
                form.instance.original_club = original_club
                form.instance.target_club = target_club
                form.instance.status = 'orig_president_pending'
                response = super().form_valid(form)
                form.instance.send_notification()
        except IntegrityError:
            messages.error(self.request, '您已有進行中的轉社申請，請勿重複送出。')
            return redirect('my_requests')
        
        messages.success(self.request, '轉社申請已成功提交，等待原社長審核')
        return response


class MyRequestsView(LoginRequiredMixin, StudentRequiredMixin, ListView):
    """
    查看個人申請進度
    """
    model = TransferRequest
    template_name = 'transfers/my_requests.html'
    context_object_name = 'requests'
    
    def get_queryset(self):
        return TransferRequest.objects.filter(
            student=self.request.user
        ).prefetch_related('approval_logs')


class RequestDetailView(LoginRequiredMixin, DetailView):
    """
    申請單詳細資訊
    """
    model = TransferRequest
    template_name = 'transfers/request_detail.html'
    context_object_name = 'request'

    def get_object(self, queryset=None):
        transfer_request = super().get_object(queryset)
        user = self.request.user

        if transfer_request.student == user:
            return transfer_request

        if is_training_admin(user):
            return transfer_request

        if transfer_request.can_be_approved_by(user):
            return transfer_request

        raise PermissionDenied
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['logs'] = self.object.approval_logs.all()
        context['current_approver'] = self.object.get_current_approver()
        user = self.request.user
        if is_training_admin(user):
            context['return_url_name'] = 'all_requests'
            context['return_label'] = '返回全校申請'
        elif can_review_transfer_requests(user):
            context['return_url_name'] = 'pending_approvals'
            context['return_label'] = '返回待審核申請'
        else:
            context['return_url_name'] = 'my_requests'
            context['return_label'] = '返回我的申請'
        return context


class ReselectClubView(LoginRequiredMixin, TransferApplicantRequiredMixin, UpdateView):
    """
    退回重選新社團
    """
    model = TransferRequest
    template_name = 'transfers/reselect_form.html'
    fields = ['target_club']
    
    def get_queryset(self):
        # 只能修改自己的申請且狀態為 returned
        return TransferRequest.objects.filter(
            student=self.request.user,
            status='returned'
        )
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        
        # 過濾可選社團
        available_clubs = Club.objects.filter(is_active=True).annotate(
            actual_members=models.Count(
                'members',
                filter=models.Q(
                    members__role__in=['student', 'president'],
                    members__is_active=True,
                ),
            )
        ).filter(
            actual_members__lt=models.F('max_members')
        ).exclude(id=self.object.original_club.id)
        
        form.fields['target_club'].queryset = available_clubs
        form.fields['target_club'].label = '重新選擇目標社團'
        
        return form
    
    def form_valid(self, form):
        with transaction.atomic():
            transfer_request = TransferRequest.objects.select_for_update().select_related(
                'student', 'original_club', 'target_club'
            ).get(pk=self.object.pk, student=self.request.user, status='returned')
            student = User.objects.select_for_update().get(pk=self.request.user.pk)
            original_club = Club.objects.select_for_update().get(
                pk=transfer_request.original_club_id
            )
            target_club = Club.objects.select_for_update().filter(
                pk=form.cleaned_data['target_club'].pk,
                is_active=True,
            ).first()

            if not student.is_active or student.role != 'student' or student.club_id != original_club.pk:
                messages.error(self.request, '您的帳號或社團狀態已變更，無法重新選擇社團。')
                return redirect('my_requests')
            if not original_club.is_active:
                messages.error(self.request, '原社團已停用，無法重新選擇社團。')
                return redirect('my_requests')
            if not target_club or target_club.pk == original_club.pk:
                messages.error(self.request, '目標社團無效或與原社團相同。')
                return redirect('my_requests')
            if target_club.get_actual_member_count() >= target_club.max_members:
                messages.error(self.request, '目標社團已額滿。')
                return redirect('my_requests')

            transfer_request.approval_logs.filter(
                approval_stage__in=['new_president_pending', 'new_teacher_pending']
            ).delete()
            transfer_request.target_club = target_club
            transfer_request.status = 'new_president_pending'
            transfer_request.save(update_fields=['target_club', 'status', 'updated_at'])
            transfer_request.send_notification()
            self.object = transfer_request
        
        messages.success(self.request, '已重新選擇目標社團，等待新社長審核')
        return redirect('my_requests')


class PendingApprovalsView(LoginRequiredMixin, ApproverRequiredMixin, ListView):
    """
    查看待審核申請
    """
    model = TransferRequest
    template_name = 'transfers/pending_approvals.html'
    context_object_name = 'pending_requests'
    
    def get_queryset(self):
        user = self.request.user
        
        if is_training_admin(user):
            # 管理員查看所有待核定申請
            return TransferRequest.objects.filter(status='admin_pending')
        
        # 社長/老師查看需要他們審核的申請
        username_marker = f'({user.username})'

        if user.role == 'president':
            return TransferRequest.objects.filter(
                models.Q(
                    status='orig_president_pending',
                    original_club_id=user.club_id,
                    original_club__president__icontains=username_marker,
                ) |
                models.Q(
                    status='new_president_pending',
                    target_club_id=user.club_id,
                    target_club__president__icontains=username_marker,
                )
            ).distinct()

        if user.role == 'teacher':
            return TransferRequest.objects.filter(
                models.Q(
                    status='orig_teacher_pending',
                    original_club__teacher__icontains=username_marker,
                ) |
                models.Q(
                    status='new_teacher_pending',
                    target_club__teacher__icontains=username_marker,
                )
            ).distinct()

        return TransferRequest.objects.none()


class ApproveRequestView(LoginRequiredMixin, View):
    """
    核准申請
    """
    def post(self, request, pk):
        with transaction.atomic():
            transfer_request = get_object_or_404(
                TransferRequest.objects.select_for_update().select_related(
                    'student', 'original_club', 'target_club'
                ),
                pk=pk,
            )

            if transfer_request.status not in REVIEWABLE_STATUSES:
                messages.error(request, '此申請目前不能審核，可能已核准、拒絕或退回。')
                return redirect('pending_approvals')

            transfer_request.student = User.objects.select_for_update().get(
                pk=transfer_request.student_id
            )
            transfer_request.original_club = Club.objects.select_for_update().get(
                pk=transfer_request.original_club_id
            )
            transfer_request.target_club = Club.objects.select_for_update().get(
                pk=transfer_request.target_club_id
            )
            state_error = get_transfer_state_error(transfer_request)
            if state_error:
                messages.error(request, state_error)
                return redirect('pending_approvals')

            if (
                transfer_request.status == 'admin_pending'
                and not is_training_admin(request.user)
            ) or (
                transfer_request.status != 'admin_pending'
                and not transfer_request.can_be_approved_by(request.user)
            ):
                messages.error(request, '您不是此申請目前階段的審核人。')
                return redirect('home')

            approval_stage = transfer_request.status

            # 最後核准階段：更新社團人數
            if transfer_request.status == 'admin_pending':
                if not transfer_request.target_club.has_available_slots():
                    messages.error(request, '目標社團已額滿，無法核准此轉社申請。')
                    return redirect('pending_approvals')

                student = transfer_request.student
                student.club = transfer_request.target_club
                student.save(update_fields=['club'])
                sync_member_counts(
                    transfer_request.original_club,
                    transfer_request.target_club,
                )
                
                transfer_request.completed_at = timezone.now()
            
            # 推進到下一階段
            if not transfer_request.advance_status():
                transaction.set_rollback(True)
                messages.error(request, '申請狀態無法前進，請重新整理後再試。')
                return redirect('pending_approvals')

            # 記錄審核
            ApprovalLog.objects.create(
                transfer_request=transfer_request,
                approver=request.user,
                approval_stage=approval_stage,
                result='approve',
                comment=request.POST.get('comment', '')
            )
        
        messages.success(request, '申請已核准')
        return redirect('pending_approvals')


class RejectRequestView(LoginRequiredMixin, View):
    """
    拒絕/退回申請
    """
    def post(self, request, pk):
        action = request.POST.get('action', 'reject')
        comment = request.POST.get('comment', '')

        if action not in ['reject', 'return']:
            action = 'reject'
        
        with transaction.atomic():
            transfer_request = get_object_or_404(
                TransferRequest.objects.select_for_update(),
                pk=pk,
            )

            if transfer_request.status not in REVIEWABLE_STATUSES:
                messages.error(request, '此申請目前不能審核，可能已核准、拒絕或退回。')
                return redirect('pending_approvals')

            if (
                transfer_request.status == 'admin_pending'
                and not is_training_admin(request.user)
            ) or (
                transfer_request.status != 'admin_pending'
                and not transfer_request.can_be_approved_by(request.user)
            ):
                messages.error(request, '您不是此申請目前階段的審核人。')
                return redirect('home')

            approval_stage = transfer_request.status

            # 記錄審核
            ApprovalLog.objects.create(
                transfer_request=transfer_request,
                approver=request.user,
                approval_stage=approval_stage,
                result='reject' if action == 'reject' else 'return',
                comment=comment
            )
            
            if action == 'return' and transfer_request.status in ['new_president_pending', 'new_teacher_pending']:
                # 退回重選新社團
                transfer_request.return_to_target_selection()
                messages.success(request, '申請已退回，學生可以重新選擇目標社團')
            else:
                # 直接拒絕
                transfer_request.reject()
                messages.success(request, '申請已拒絕')
        
        return redirect('pending_approvals')


class AllRequestsView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    """
    管理員查看全校所有申請
    """
    model = TransferRequest
    template_name = 'transfers/all_requests.html'
    context_object_name = 'requests'
    
    def get_queryset(self):
        return TransferRequest.objects.all().select_related(
            'student', 'original_club', 'target_club'
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_requests = TransferRequest.objects.all()
        
        context['total_count'] = all_requests.count()
        context['approved_count'] = all_requests.filter(status='approved').count()
        context['rejected_count'] = all_requests.filter(status='rejected').count()
        context['in_progress_count'] = all_requests.exclude(
            status__in=['approved', 'rejected']
        ).count()
        
        return context


class DeleteRequestRecordView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'transfers/request_confirm_delete.html'

    def get(self, request, pk):
        transfer_request = get_object_or_404(
            TransferRequest.objects.select_related('student', 'original_club', 'target_club'),
            pk=pk,
        )
        approval_log_count = transfer_request.approval_logs.count()
        return render(
            request,
            self.template_name,
            {
                'transfer_request': transfer_request,
                'approval_log_count': approval_log_count,
            },
        )

    def post(self, request, pk):
        transfer_request = get_object_or_404(TransferRequest, pk=pk)
        request_id = transfer_request.pk

        with transaction.atomic():
            ApprovalLog.objects.filter(transfer_request=transfer_request).delete()
            transfer_request.delete()

        messages.success(request, f'申請紀錄 #{request_id} 已刪除。')
        return redirect('all_requests')


class DeleteAllRequestRecordsView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request):
        request_ids = list(TransferRequest.objects.values_list('pk', flat=True))
        deleted_count = len(request_ids)

        if deleted_count:
            with transaction.atomic():
                ApprovalLog.objects.filter(transfer_request_id__in=request_ids).delete()
                TransferRequest.objects.filter(pk__in=request_ids).delete()

        messages.success(request, f'已刪除 {deleted_count} 筆全校申請紀錄。')
        return redirect('all_requests')
