import os
import sys
from pathlib import Path

# manage.py adds the project folder (the one that holds core/) to the import path; a production server
# (gunicorn, waitress) starts from here instead, so do the same.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from django.core.wsgi import get_wsgi_application  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()
