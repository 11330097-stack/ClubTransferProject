from .services import get_transfer_window_state
from .models import TransferRequest


def transfer_window(request):
    context = get_transfer_window_state()
    user = getattr(request, 'user', None)
    context['admin_pending_review_count'] = 0

    if user and user.is_authenticated and (
        user.is_superuser or getattr(user, 'role', None) == 'admin'
    ):
        context['admin_pending_review_count'] = TransferRequest.objects.filter(
            status__in=[
                'orig_president_pending',
                'orig_teacher_pending',
                'new_president_pending',
                'new_teacher_pending',
                'admin_pending',
            ],
        ).count()

    return context
