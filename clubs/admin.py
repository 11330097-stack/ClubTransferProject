from django.contrib import admin
from .models import Club


@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = ['name', 'teacher', 'president', 'max_members', 'current_members', 'get_remaining', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'description']
    
    def get_remaining(self, obj):
        return obj.get_remaining_slots()
    get_remaining.short_description = '剩餘名額'
