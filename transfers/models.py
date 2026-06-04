from django.db import models
from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone
import re


def get_user_from_display_text(value):
    """Resolve a User from text like '學生001 (student001)'."""
    if not value:
        return None

    if not isinstance(value, str):
        return value

    match = re.search(r'\(([^()]+)\)\s*$', value.strip())
    username = match.group(1).strip() if match else value.strip()
    if not username:
        return None

    from django.apps import apps

    app_label, model_name = settings.AUTH_USER_MODEL.split('.', 1)
    User = apps.get_model(app_label, model_name)
    try:
        return User.objects.get(username=username)
    except User.DoesNotExist:
        return None


class TransferWindow(models.Model):
    """
    系統層級的轉社申請期間設定。
    """
    start_date = models.DateField(verbose_name='轉社開始日期')
    end_date = models.DateField(verbose_name='轉社結束日期')
    is_paused = models.BooleanField(default=False, verbose_name='暫停轉社期')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新時間')

    class Meta:
        verbose_name = '轉社期限設定'
        verbose_name_plural = '轉社期限設定'

    def __str__(self):
        return f'{self.start_date:%Y/%m/%d} ~ {self.end_date:%Y/%m/%d}'

    @classmethod
    def get_current(cls):
        return cls.objects.order_by('-updated_at', '-pk').first()

    def is_open(self, today=None):
        if self.is_paused:
            return False
        today = today or timezone.localdate()
        return self.start_date <= today <= self.end_date

    def get_status(self, today=None):
        if self.is_paused:
            return 'paused'
        today = today or timezone.localdate()
        if today < self.start_date:
            return 'not_started'
        if today > self.end_date:
            return 'ended'
        return 'open'

    @property
    def status_text(self):
        status = self.get_status()
        if status == 'paused':
            return '已暫停'
        if status == 'not_started':
            return '尚未開始'
        if status == 'ended':
            return '已截止'
        return '開放中'


class TransferRecordArchive(models.Model):
    transfer_window = models.ForeignKey(
        TransferWindow,
        on_delete=models.PROTECT,
        related_name='record_archives',
        verbose_name='轉社期',
    )
    title = models.CharField(max_length=100, verbose_name='名稱')
    start_date = models.DateField(verbose_name='開始日期')
    end_date = models.DateField(verbose_name='結束日期')
    archived_at = models.DateTimeField(auto_now_add=True, verbose_name='儲存時間')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_transfer_record_archives',
        verbose_name='儲存者',
    )

    class Meta:
        verbose_name = '轉社紀錄批次'
        verbose_name_plural = '轉社紀錄批次'
        ordering = ['-archived_at']
        constraints = [
            models.UniqueConstraint(
                fields=['transfer_window', 'start_date', 'end_date'],
                name='unique_archive_per_transfer_window_period',
            ),
        ]

    def __str__(self):
        return self.title


class TransferRecordSnapshot(models.Model):
    archive = models.ForeignKey(
        TransferRecordArchive,
        on_delete=models.CASCADE,
        related_name='snapshots',
        verbose_name='轉社紀錄批次',
    )
    student_name = models.CharField(max_length=150, verbose_name='學生')
    student_username = models.CharField(max_length=150, verbose_name='帳號')
    student_id = models.CharField(max_length=20, blank=True, verbose_name='學號')
    original_club_name = models.CharField(max_length=100, verbose_name='原社團')
    target_club_name = models.CharField(max_length=100, verbose_name='新社團')
    status = models.CharField(max_length=30, verbose_name='狀態')
    submitted_at = models.DateTimeField(verbose_name='申請時間')
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name='核准或更新時間')
    approval_summary = models.TextField(blank=True, verbose_name='審核摘要')

    class Meta:
        verbose_name = '轉社紀錄快照'
        verbose_name_plural = '轉社紀錄快照'
        ordering = ['submitted_at', 'pk']

    def __str__(self):
        return f'{self.student_name}: {self.original_club_name} → {self.target_club_name}'


class TransferRequest(models.Model):
    """
    轉社申請單模型
    多階層序位審核流程：原社長 → 原老師 → 新社長 → 新老師 → 訓育組
    """
    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('orig_president_pending', '原社長審核中'),
        ('orig_teacher_pending', '原指導老師審核中'),
        ('new_president_pending', '新社長審核中'),
        ('new_teacher_pending', '新指導老師審核中'),
        ('admin_pending', '訓育組審核中'),
        ('approved', '已核准'),
        ('rejected', '已拒絕'),
        ('returned', '退回重選'),
    ]
    
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='transfer_requests',
        verbose_name='申請學生'
    )
    original_club = models.ForeignKey(
        'clubs.Club',
        on_delete=models.CASCADE,
        related_name='transfer_out_requests',
        verbose_name='原社團'
    )
    target_club = models.ForeignKey(
        'clubs.Club',
        on_delete=models.CASCADE,
        related_name='transfer_in_requests',
        verbose_name='目標社團'
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default='orig_president_pending',
        verbose_name='狀態'
    )
    reason = models.TextField(blank=True, verbose_name='轉社原因')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='申請時間')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新時間')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成時間')
    
    class Meta:
        verbose_name = '轉社申請單'
        verbose_name_plural = '轉社申請單'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.student} - {self.original_club} → {self.target_club} ({self.get_status_display()})"
    
    def get_current_approver(self):
        """取得目前應該審核的人"""
        approvers = {
            'orig_president_pending': self.original_club.president,
            'orig_teacher_pending': self.original_club.teacher,
            'new_president_pending': self.target_club.president,
            'new_teacher_pending': self.target_club.teacher,
            'admin_pending': None,  # 訓育組為管理員群組
        }
        return get_user_from_display_text(approvers.get(self.status))
    
    def advance_status(self):
        """推進到下一個審核階段"""
        flow = [
            'orig_president_pending',
            'orig_teacher_pending',
            'new_president_pending',
            'new_teacher_pending',
            'admin_pending',
            'approved',
        ]
        
        if self.status not in flow:
            return False

        current_index = flow.index(self.status)
        if current_index < len(flow) - 1:
            self.status = flow[current_index + 1]
            self.save()
            self.send_notification()
            return True
        return False
    
    def return_to_target_selection(self):
        """退回重選新社團"""
        # 保留原社團審核結果，回到新社長審核階段讓學生重選
        self.status = 'returned'
        self.save()
    
    def reject(self):
        """拒絕申請"""
        self.status = 'rejected'
        self.save()
    
    def can_be_approved_by(self, user):
        """檢查使用者是否有權限核准此階段"""
        current_approver = self.get_current_approver()
        
        if self.status == 'admin_pending':
            return user.is_admin()
        
        return current_approver == user
    
    def send_notification(self):
        """發送通知給下一個審核者"""
        approver = self.get_current_approver()
        
        if approver and getattr(approver, 'email', None):
            subject = f'【社團轉社系統】有新的轉社申請需要審核'
            message = f'''
您好，{approver.get_full_name() or approver.username}：

有一筆轉社申請需要您的審核：

申請學生：{self.student.get_full_name() or self.student.username} ({self.student.student_id})
原社團：{self.original_club.name}
目標社團：{self.target_club.name}
申請時間：{self.created_at.strftime('%Y-%m-%d %H:%M')}

請登入系統查看詳情並進行審核。
            '''
            send_mail(
                subject=subject,
                message=message,
                from_email='noreply@clubtransfer.edu.tw',
                recipient_list=[approver.email],
                fail_silently=True,
            )
        elif self.status == 'approved':
            # 通知學生申請已完成
            if self.student.email:
                subject = f'【社團轉社系統】您的轉社申請已核准'
                message = f'''
您好，{self.student.get_full_name() or self.student.username}：

您的轉社申請已經完成所有審核並核准：

原社團：{self.original_club.name}
新社團：{self.target_club.name}
核准時間：{self.updated_at.strftime('%Y-%m-%d %H:%M')}

請於下次社團活動時前往新社團報到。
                '''
                send_mail(
                    subject=subject,
                    message=message,
                    from_email='noreply@clubtransfer.edu.tw',
                    recipient_list=[self.student.email],
                    fail_silently=True,
                )


class ApprovalLog(models.Model):
    """
    審核紀錄模型
    """
    RESULT_CHOICES = [
        ('approve', '同意'),
        ('reject', '拒絕'),
        ('return', '退回重選'),
    ]
    
    transfer_request = models.ForeignKey(
        TransferRequest,
        on_delete=models.CASCADE,
        related_name='approval_logs',
        verbose_name='申請單'
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name='審核人'
    )
    approval_stage = models.CharField(
        max_length=30,
        verbose_name='審核階段'
    )
    result = models.CharField(
        max_length=10,
        choices=RESULT_CHOICES,
        verbose_name='審核結果'
    )
    comment = models.TextField(blank=True, verbose_name='審核意見')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='審核時間')
    
    class Meta:
        verbose_name = '審核紀錄'
        verbose_name_plural = '審核紀錄'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.transfer_request} - {self.approver} ({self.get_result_display()})"
