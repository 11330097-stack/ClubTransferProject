from django.contrib import admin
from .models import TransferRequest, ApprovalLog, TransferWindow


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
    list_display = ['start_date', 'end_date', 'updated_at']
