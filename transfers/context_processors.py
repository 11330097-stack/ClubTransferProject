from .services import get_transfer_window_state


def transfer_window(request):
    return get_transfer_window_state()
