from .models import TransferWindow


def get_transfer_window_state():
    transfer_window = TransferWindow.get_current()
    is_open = transfer_window.is_open() if transfer_window else False
    status = transfer_window.get_status() if transfer_window else 'not_configured'

    return {
        'transfer_window': transfer_window,
        'transfer_window_is_open': is_open,
        'transfer_window_status': status,
        'transfer_window_is_paused': status == 'paused',
    }
