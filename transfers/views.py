from django.views.generic import ListView, DetailView, CreateView, UpdateView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.contrib import messages
from django.db import transaction, models
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from .models import TransferRequest, ApprovalLog
from clubs.models import Club
from accounts.models import User


class StudentRequiredMixin(UserPassesTestMixin):
    """檢查是否為學生"""
    def test_func(self):
        return self.request.user.role in ['student', 'president']


class ApproverRequiredMixin(UserPassesTestMixin):
    """檢查是否為審核者（社長、老師、管理員）"""
    def test_func(self):
        return self.request.user.role in ['president', 'teacher', 'admin']


class AdminRequiredMixin(UserPassesTestMixin):
    """檢查是否為訓育組管理員"""
    def test_func(self):
        return self.request.user.is_admin()


class TransferApplyView(LoginRequiredMixin, StudentRequiredMixin, CreateView):
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
        if user.club:
            available_clubs = Club.objects.filter(
                is_active=True,
                current_members__lt=models.F('max_members')
            ).exclude(id=user.club.id)
        else:
            available_clubs = Club.objects.filter(
                is_active=True,
                current_members__lt=models.F('max_members')
            )
        
        form.fields['target_club'].queryset = available_clubs
        form.fields['target_club'].label = '目標社團'
        form.fields['target_club'].empty_label = '請選擇社團'
        form.fields['reason'].label = '轉社原因'
        form.fields['reason'].widget.attrs['rows'] = 4
        
        return form
    
    def form_valid(self, form):
        user = self.request.user
        
        if not user.club:
            messages.error(self.request, '您目前沒有所屬社團，無法申請轉社')
            return redirect('transfer_apply')
        
        # 檢查是否有進行中的申請
        existing = TransferRequest.objects.filter(
            student=user,
            status__in=['orig_president_pending', 'orig_teacher_pending', 
                       'new_president_pending', 'new_teacher_pending', 
                       'admin_pending', 'returned']
        ).first()
        
        if existing:
            messages.error(self.request, f'您已有進行中的轉社申請（{existing.get_status_display()}），請先完成或取消該申請')
            return redirect('my_requests')
        
        form.instance.student = user
        form.instance.original_club = user.club
        form.instance.status = 'orig_president_pending'
        
        response = super().form_valid(form)
        
        # 發送通知給原社長
        form.instance.send_notification()
        
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

        if user.is_admin():
            return transfer_request

        if transfer_request.can_be_approved_by(user):
            return transfer_request

        raise PermissionDenied
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['logs'] = self.object.approval_logs.all()
        context['current_approver'] = self.object.get_current_approver()
        return context


class ReselectClubView(LoginRequiredMixin, StudentRequiredMixin, UpdateView):
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
        available_clubs = Club.objects.filter(
            is_active=True,
            current_members__lt=models.F('max_members')
        ).exclude(id=self.object.original_club.id)
        
        form.fields['target_club'].queryset = available_clubs
        form.fields['target_club'].label = '重新選擇目標社團'
        
        return form
    
    def form_valid(self, form):
        # 清除之前新社團的審核紀錄
        self.object.approval_logs.filter(
            approval_stage__in=['new_president_pending', 'new_teacher_pending']
        ).delete()
        
        # 重新進入新社長審核階段
        self.object.status = 'new_president_pending'
        self.object.save()
        
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
        
        if user.is_admin():
            # 管理員查看所有待核定申請
            return TransferRequest.objects.filter(status='admin_pending')
        
        # 社長/老師查看需要他們審核的申請
        username_marker = f'({user.username})'

        if user.role == 'president':
            return TransferRequest.objects.filter(
                models.Q(
                    status='orig_president_pending',
                    original_club__president__icontains=username_marker,
                ) |
                models.Q(
                    status='new_president_pending',
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
        transfer_request = get_object_or_404(TransferRequest, pk=pk)
        
        if not transfer_request.can_be_approved_by(request.user):
            messages.error(request, '您沒有權限核准此申請')
            return redirect('home')
        
        # 記錄審核
        ApprovalLog.objects.create(
            transfer_request=transfer_request,
            approver=request.user,
            approval_stage=transfer_request.status,
            result='approve',
            comment=request.POST.get('comment', '')
        )
        
        with transaction.atomic():
            # 最後核准階段：更新社團人數
            if transfer_request.status == 'admin_pending':
                transfer_request.original_club.decrement_members()
                transfer_request.target_club.increment_members()
                
                # 更新學生所屬社團
                student = transfer_request.student
                student.club = transfer_request.target_club
                student.save()
                
                transfer_request.completed_at = timezone.now()
            
            # 推進到下一階段
            transfer_request.advance_status()
        
        messages.success(request, '申請已核准')
        return redirect('pending_approvals')


class RejectRequestView(LoginRequiredMixin, View):
    """
    拒絕/退回申請
    """
    def post(self, request, pk):
        transfer_request = get_object_or_404(TransferRequest, pk=pk)
        action = request.POST.get('action', 'reject')
        comment = request.POST.get('comment', '')
        
        if not transfer_request.can_be_approved_by(request.user):
            messages.error(request, '您沒有權限處理此申請')
            return redirect('home')
        
        with transaction.atomic():
            # 記錄審核
            ApprovalLog.objects.create(
                transfer_request=transfer_request,
                approver=request.user,
                approval_stage=transfer_request.status,
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
