"""Serves the small web app (one HTML page, one script, one stylesheet) from backend/web/."""

from pathlib import Path

from django.http import Http404, HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
FILES = {  # only these names can be requested; nothing is built from the URL
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "i18n.js": "text/javascript; charset=utf-8",
    "legal.js": "text/javascript; charset=utf-8",
}
# No inline scripts or styles, nothing from other sites. The CV preview is an iframe of our own page.
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; "
       "frame-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")


def _serve(name):
    if name not in FILES:
        raise Http404()
    response = HttpResponse((WEB_DIR / name).read_bytes(), content_type=FILES[name])
    response["Content-Security-Policy"] = CSP
    response["X-Frame-Options"] = "DENY"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
@never_cache
def index(request):
    return _serve("index.html")


@require_GET
@never_cache
def asset(request, name):
    return _serve(name)
