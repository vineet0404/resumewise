"""Share link and LinkedIn help for one CV (step 13).

Share link: a secret address (/s/<token>) that shows a read-only copy of the CV, without logging in. Safe defaults:
phone, email and photo are hidden until the owner ticks them; search engines are told not to index it; the owner can turn
it off at any time; it stops working when the CV is deleted (30 days). We count how many times it was opened, nothing else
(no addresses, no names).
"""

import copy
import secrets
from datetime import datetime  # noqa: F401  (kept for readers: expiry uses profile.expires_at)

from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from core import linkedin, profile_edit, render

from . import throttle
from .auth_views import _client_ip
from .models import Profile, ProfilePhoto
from .profile_views import _not_found
from .views import api_login_required, read_json_body

PUBLIC_FAILS = 30  # unknown-address tries per IP per window before we slow down guessing


def _status(profile):
    on = bool(profile.share_token)
    return {"shared": on, "path": "/s/" + profile.share_token if on else None, "views": profile.share_views,
            "show_contact": profile.share_contact, "show_photo": profile.share_photo,
            "template": profile.share_template or profile.template_key}


def _own(request, profile_id):
    return Profile.objects.filter(id=profile_id, user=request.user).first()


@require_http_methods(["GET", "PUT", "DELETE"])
@api_login_required
def share(request, profile_id):
    profile = _own(request, profile_id)
    if profile is None:
        return _not_found()
    if request.method == "GET":
        return JsonResponse(_status(profile))
    if request.method == "DELETE":
        profile.share_token, profile.share_views = None, 0
        profile.save(update_fields=["share_token", "share_views"])
        return JsonResponse(_status(profile))
    data, error = read_json_body(request, [])
    if error:
        return error
    template = data.get("template", profile.share_template or profile.template_key)
    if template not in render.TEMPLATES:
        return JsonResponse({"error": "unknown template"}, status=400)
    for key in ("show_contact", "show_photo"):
        if key in data and not isinstance(data[key], bool):
            return JsonResponse({"error": key + " must be true or false"}, status=400)
    created = not profile.share_token
    if created:
        profile.share_token = secrets.token_urlsafe(24)
    profile.share_template = template
    profile.share_contact = data.get("show_contact", profile.share_contact)
    profile.share_photo = data.get("show_photo", profile.share_photo)
    profile.save(update_fields=["share_token", "share_template", "share_contact", "share_photo"])
    return JsonResponse(_status(profile), status=201 if created else 200)


def shared_page(request, token):
    """The public page. Anyone with the address can open it; nobody can find it without the address."""
    ip = _client_ip(request)
    limit = throttle.ip_limit(PUBLIC_FAILS)
    if throttle.is_blocked("share", ip, limit=limit):
        return HttpResponse("Too many tries. Please wait a few minutes.", status=429, content_type="text/plain")
    profile = Profile.objects.filter(share_token=token).first() if 20 <= len(token) <= 64 else None
    if profile is not None and profile.expires_at is not None and profile.expires_at <= timezone.now():
        profile = None
    if profile is None:
        throttle.record_failure("share", ip)
        response = HttpResponse("This link is not available. The owner may have turned it off.", status=404, content_type="text/plain")
        response["X-Robots-Tag"] = "noindex"
        return response
    parsed = profile_edit.with_contact(profile.parsed)
    if not profile.share_contact:
        parsed = copy.deepcopy(parsed)
        parsed["contact"]["email"] = ""
        parsed["contact"]["phone"] = ""
    template = profile.share_template if profile.share_template in render.TEMPLATES else profile.template_key
    photo = None
    if profile.share_photo and render.TEMPLATES[template]["photo"]:
        row = ProfilePhoto.objects.filter(profile=profile).first()
        if row is not None:
            photo = {"content_type": row.content_type, "data": bytes(row.data)}
    html = render.render_resume_html(parsed, template, photo)
    Profile.objects.filter(pk=profile.pk).update(share_views=F("share_views") + 1)
    response = HttpResponse(html, content_type="text/html; charset=utf-8")
    response["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; frame-ancestors 'none'"
    response["X-Frame-Options"] = "DENY"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["Referrer-Policy"] = "no-referrer"
    response["Cache-Control"] = "no-store"
    return response


@require_GET
@api_login_required
def linkedin_help(request, profile_id):
    profile = _own(request, profile_id)
    if profile is None:
        return _not_found()
    target = request.GET.get("target", "")
    if len(target) > 80:
        return JsonResponse({"error": "the role is too long (limit 80 characters)"}, status=400)
    return JsonResponse(linkedin.advise(profile.parsed, target))
