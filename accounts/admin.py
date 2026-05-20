from django.contrib import admin
from django.contrib import messages
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from .models import User
from .services import SAMPLE_STUDENT_IMPORT_CSV, import_students_from_csv


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    change_list_template = 'admin/accounts/user/change_list.html'
    list_display = ['username', 'student_id', 'get_full_name', 'role', 'club', 'is_active']
    list_filter = ['role', 'is_active', 'club']
    search_fields = ['username', 'student_id', 'first_name', 'last_name']

    fieldsets = UserAdmin.fieldsets + (
        ('社團資訊', {
            'fields': ('role', 'student_id', 'club'),
        }),
    ) # pyright: ignore[reportAssignmentType, reportOperatorIssue]

    add_fieldsets = UserAdmin.add_fieldsets + (
        ('社團資訊', {
            'fields': ('role', 'student_id', 'club'),
        }),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'import-students-csv/',
                self.admin_site.admin_view(self.import_students_csv_view),
                name='accounts_user_import_students_csv',
            ),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['can_import_students_csv'] = self.has_import_permission(request)
        extra_context['import_students_csv_url'] = reverse('admin:accounts_user_import_students_csv')
        return super().changelist_view(request, extra_context=extra_context)

    def has_import_permission(self, request):
        user = request.user
        return user.is_superuser or getattr(user, 'role', None) == 'admin'

    def import_students_csv_view(self, request):
        if not self.has_import_permission(request):
            raise PermissionDenied

        context = {
            **self.admin_site.each_context(request),
            'title': '匯入學生 CSV',
            'opts': self.model._meta,
            'sample_csv': SAMPLE_STUDENT_IMPORT_CSV,
            'result': None,
        }

        if request.method == 'POST':
            csv_file = request.FILES.get('csv_file')
            if not csv_file:
                messages.error(request, '請選擇 CSV 檔案。')
                return redirect('admin:accounts_user_import_students_csv')

            context['result'] = import_students_from_csv(csv_file)

        return TemplateResponse(
            request,
            'admin/accounts/user/import_students_csv.html',
            context,
        )
