from django.contrib import admin
from .models import (
    ApprovalLog,
    TransferRecordArchive,
    TransferRecordSnapshot,
    TransferRequest,
    TransferWindow,
)


class ApprovalLogInline(admin.TabularInline):
    model = ApprovalLog
    extra = 0
    readonly_fields = ['created_at']
    fields = ['approver', 'approval_stage', 'result', 'comment', 'created_at']


@admin.register(TransferRequest)
class TransferRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'student', 'original_club', 'target_club', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['student__username', 'student__student_id', 'original_club__name', 'target_club__name']
    inlines = [ApprovalLogInline]


@admin.register(ApprovalLog)
class ApprovalLogAdmin(admin.ModelAdmin):
    list_display = ['transfer_request', 'approver', 'approval_stage', 'result', 'created_at']
    list_filter = ['result', 'created_at']


@admin.register(TransferWindow)
class TransferWindowAdmin(admin.ModelAdmin):
    list_display = ['start_date', 'end_date', 'is_paused', 'updated_at']


class TransferRecordSnapshotInline(admin.TabularInline):
    model = TransferRecordSnapshot
    extra = 0
    readonly_fields = [
        'student_name',
        'student_username',
        'student_id',
        'original_club_name',
        'target_club_name',
        'status',
        'submitted_at',
        'approved_at',
        'approval_summary',
    ]
    fields = readonly_fields
    can_delete = False


@admin.register(TransferRecordArchive)
class TransferRecordArchiveAdmin(admin.ModelAdmin):
    list_display = ['title', 'start_date', 'end_date', 'archived_at', 'created_by']
    list_filter = ['archived_at', 'start_date', 'end_date']
    search_fields = ['title']
    inlines = [TransferRecordSnapshotInline]


@admin.register(TransferRecordSnapshot)
class TransferRecordSnapshotAdmin(admin.ModelAdmin):
    list_display = [
        'student_name',
        'student_id',
        'original_club_name',
        'target_club_name',
        'status',
        'submitted_at',
    ]
    list_filter = ['status', 'submitted_at']
    search_fields = ['student_name', 'student_username', 'student_id', 'original_club_name', 'target_club_name']
