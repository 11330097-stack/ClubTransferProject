from django.shortcuts import render


def permission_denied(request, exception=None):
    return render(request, '403.html', status=403)


def page_not_found(request, exception=None):
    return render(request, '404.html', status=404)


def server_error(request):
    return render(request, '500.html', status=500)


def csrf_failure(request, reason=''):
    return render(request, '403_csrf.html', status=403)
