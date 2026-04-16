"""
WSGI config for club_transfer project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'club_transfer.settings')

application = get_wsgi_application()
