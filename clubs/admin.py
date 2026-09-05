from django.contrib import admin
from .models import Club


@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = ['name', 'teacher', 'president', 'max_members', 'current_members', 'get_remaining', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'description']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        if obj is None:
            return super().has_change_permission(request, obj)
        return False

    def has_delete_permission(self, request, obj=None):
        # Club mutations must use the project workflow so president, teacher,
        # membership, capacity, and transfer-history rules are enforced.
        return False
    
    def get_remaining(self, obj):
        return obj.get_remaining_slots()
    get_remaining.short_description = '剩餘名額'
