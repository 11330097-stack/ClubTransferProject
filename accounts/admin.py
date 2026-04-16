from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'student_id', 'get_full_name', 'role', 'club', 'is_active']
    list_filter = ['role', 'is_active', 'club']
    search_fields = ['username', 'student_id', 'first_name', 'last_name']
    
    fieldsets = UserAdmin.fieldsets + (
        ('社團資訊', {
            'fields': ('role', 'student_id', 'club', 'phone'),
        }),
    )
    
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('社團資訊', {
            'fields': ('role', 'student_id', 'club', 'phone'),
        }),
    )
