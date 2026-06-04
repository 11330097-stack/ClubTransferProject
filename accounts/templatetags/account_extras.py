from django import template

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
    if getattr(user, 'role', None) == 'president' and not user_is_club_president(user, user.club):
        return '學生'
    return user.get_role_display()


@register.simple_tag
def is_club_president(user, club):
    return user_is_club_president(user, club)
