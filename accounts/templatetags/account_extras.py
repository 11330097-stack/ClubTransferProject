import re

from django import template
from django.utils.safestring import mark_safe

from accounts.permissions import can_review_transfer_requests


register = template.Library()


@register.filter
def workflow_widget(field):
    """Render a bound field with consistent accessible workflow attributes."""
    widget = field.field.widget
    input_type = getattr(widget, 'input_type', '')
    existing_class = widget.attrs.get('class', '')
    control_class = 'form-check-input' if input_type in {'checkbox', 'radio'} else (
        'form-select' if input_type == 'select' else 'form-control'
    )
    classes = [existing_class, control_class]
    if field.errors:
        classes.append('is-invalid')

    described_by = []
    if field.help_text:
        described_by.append(f'{field.id_for_label}_help')
    if field.errors:
        described_by.append(f'{field.id_for_label}_errors')

    attrs = {'class': ' '.join(filter(None, classes))}
    if described_by:
        attrs['aria-describedby'] = ' '.join(described_by)
    if field.errors:
        attrs['aria-invalid'] = 'true'
    return mark_safe(field.as_widget(attrs=attrs))


def user_is_club_president(user, club):
    if not user or not club or not getattr(club, 'president', ''):
        return False

    president_text = club.president.strip()
    match = re.search(r'\(([^()]+)\)\s*$', president_text)
    president_username = match.group(1).strip() if match else president_text
    return president_username == user.username


@register.filter
def display_role(user):
    if getattr(user, 'role', None) == 'admin':
        return '訓育組長'
    if getattr(user, 'role', None) == 'president' and not user_is_club_president(user, user.club):
        return '學生'
    return user.get_role_display()


@register.simple_tag
def is_club_president(user, club):
    return user_is_club_president(user, club)


@register.filter
def can_review_transfers(user):
    return can_review_transfer_requests(user)


@register.filter
def role_badge_class(user):
    role = getattr(user, 'role', None)
    displayed_role = display_role(user)
    if role == 'president' and displayed_role == user.get_role_display():
        return 'role-badge-president'
    if role == 'teacher':
        return 'role-badge-teacher'
    if role == 'admin' or getattr(user, 'is_superuser', False):
        return 'role-badge-admin'
    return 'role-badge-student'


NAV_SECTIONS = {
    'overview': {'home'},
    'clubs': {'club_list', 'club_detail'},
    'transfer_apply': {'transfer_apply', 'reselect_club'},
    'my_requests': {'my_requests'},
    'pending_approvals': {'pending_approvals'},
    'all_requests': {'all_requests', 'delete_all_request_records'},
    'transfer_records': {
        'transfer_record_archive_list',
        'transfer_record_archive_detail',
        'transfer_record_archive_create',
    },
    'transfer_window': {
        'transfer_window_settings',
        'transfer_window_pause',
        'transfer_window_resume',
    },
    'unassigned_accounts': {
        'unassigned_account_list',
        'unassigned_student_bulk_assign_club',
        'unassigned_student_assign_club',
        'assignment_record_list',
    },
}


@register.filter
def nav_is_active(url_name, section):
    """Return whether a resolved URL belongs to a visual navigation section."""
    if not url_name:
        return False
    if section == 'club_admin':
        return url_name.startswith('club_admin_')
    if section == 'account_admin':
        return url_name.startswith(('account_admin_', 'student_admin_', 'teacher_admin_'))
    return url_name in NAV_SECTIONS.get(section, set())


@register.filter
def page_context_label(url_name):
    """Provide a quiet top-bar context label without coupling views to layout."""
    if not url_name:
        return '工作區'
    if url_name == 'home':
        return '總覽'
    if url_name in NAV_SECTIONS['clubs']:
        return '社團資訊'
    if url_name in NAV_SECTIONS['transfer_apply']:
        return '轉社申請'
    if url_name == 'my_requests':
        return '我的申請'
    if url_name in {'pending_approvals', 'approve_request', 'reject_request'}:
        return '申請審核'
    if url_name in {'all_requests', 'delete_all_request_records', 'delete_request_record'}:
        return '全校申請'
    if url_name == 'request_detail':
        return '申請詳情'
    if url_name in NAV_SECTIONS['transfer_records']:
        return '轉社紀錄'
    if url_name in NAV_SECTIONS['transfer_window']:
        return '轉社期限'
    if url_name.startswith('club_admin_'):
        return '社團管理'
    if url_name in NAV_SECTIONS['unassigned_accounts']:
        return '成員分配'
    if url_name.startswith(('account_admin_', 'student_admin_', 'teacher_admin_')):
        return '帳號管理'
    if url_name in {'profile', 'profile_password_change', 'admin_profile_edit'}:
        return '個人帳號'
    return '工作區'
