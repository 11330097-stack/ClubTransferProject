from clubs.models import Club
from transfers.models import get_user_from_display_text


def is_training_admin(user):
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or getattr(user, 'role', None) == 'admin')
    )


def display_text_matches_user(value, user):
    if not value or not user or not user.is_authenticated:
        return False

    resolved_user = get_user_from_display_text(value)
    if resolved_user:
        return resolved_user.pk == user.pk

    text = str(value).strip()
    return text == user.username or f'({user.username})' in text


def is_actual_club_president(user):
    if not user or not user.is_authenticated or getattr(user, 'role', None) != 'president':
        return False

    return any(
        display_text_matches_user(club.president, user)
        for club in Club.objects.filter(is_active=True).exclude(president='')
    )


def is_assigned_club_teacher(user):
    if not user or not user.is_authenticated or getattr(user, 'role', None) != 'teacher':
        return False

    return any(
        display_text_matches_user(club.teacher, user)
        for club in Club.objects.filter(is_active=True).exclude(teacher='')
    )


def can_review_transfer_requests(user):
    return (
        is_training_admin(user)
        or is_actual_club_president(user)
        or is_assigned_club_teacher(user)
    )
