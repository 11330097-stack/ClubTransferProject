from django import template

from accounts.permissions import can_review_transfer_requests
from transfers.models import get_user_from_display_text


register = template.Library()


def user_is_club_president(user, club):
    if not user or not club or not getattr(club, 'president', ''):
        return False

    resolved_president = get_user_from_display_text(club.president)
    if resolved_president:
        return resolved_president.pk == user.pk

    return club.president.strip() == user.username


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
