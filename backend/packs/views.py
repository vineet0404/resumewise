"""Version 1 of the JSON API. Web and the future mobile app both use these."""

import json
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core import ats, cv_builder, extract, keywords, matching, profile_edit, resume_parser

from .models import JsonTextMixin, Profile, ProfilePhoto

RETENTION_DAYS = 30


def api_login_required(view):
    """Return a JSON 401 instead of a redirect when not signed in."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "authentication required"}, status=401)
        return view(request, *args, **kwargs)

    return wrapper


def read_json_body(request, required_text_fields):
    """Return (data, error_response). Checks JSON, types and the size limit."""
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None, JsonResponse({"error": "body must be valid JSON"}, status=400)
    if not isinstance(data, dict):
        return None, JsonResponse({"error": "body must be a JSON object"}, status=400)
    for field in required_text_fields:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            return None, JsonResponse({"error": "%s must be a non-empty string" % field}, status=400)
        if len(value) > settings.MAX_TEXT_CHARS:
            return None, JsonResponse({"error": "%s is too long" % field}, status=413)
    return data, None


@require_GET
def health(request):
    """For load balancers and uptime checks: 200 when the app and its database answer, 503 otherwise (no details)."""
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # noqa: BLE001  any database failure means "not healthy"
        return JsonResponse({"status": "down"}, status=503)
    return JsonResponse({"status": "ok"})


@require_POST
@api_login_required
def match(request):
    data, error = read_json_body(request, ["resume_text", "job_text"])
    if error:
        return error
    parsed = resume_parser.parse_resume(data["resume_text"])
    requirements = keywords.extract_requirements(data["job_text"])
    result = matching.score_match(resume_parser.all_items(parsed), requirements)
    return JsonResponse(result)


@require_POST
@api_login_required
def create_profile(request):
    data, error = read_json_body(request, ["resume_text"])
    if error:
        return error
    parsed = resume_parser.parse_resume(data["resume_text"])
    profile = Profile.objects.create(
        user=request.user,
        parsed_json=JsonTextMixin.dump(parsed),
        expires_at=timezone.now() + timedelta(days=RETENTION_DAYS),
    )
    return JsonResponse({"id": str(profile.id), "parsed": parsed}, status=201)


@require_POST
@api_login_required
def build_profile(request):
    """Build a CV from the "Build from scratch" form answers (see core/cv_builder.py)."""
    data, error = read_json_body(request, [])
    if error:
        return error
    try:
        parsed = cv_builder.build(data)
    except profile_edit.EditError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    profile = Profile.objects.create(
        user=request.user,
        parsed_json=JsonTextMixin.dump(parsed),
        expires_at=timezone.now() + timedelta(days=RETENTION_DAYS),
    )
    return JsonResponse({"id": str(profile.id), "parsed": parsed}, status=201)


@require_GET
@api_login_required
def get_profile(request, profile_id):
    # Filtering by user means another user's id looks exactly like a missing one.
    profile = Profile.objects.filter(id=profile_id, user=request.user).first()
    if profile is None:
        return JsonResponse({"error": "not found"}, status=404)
    return JsonResponse({
        "id": str(profile.id),
        "parsed": profile_edit.with_contact(profile.parsed),
        "template": profile.template_key,
        "has_photo": ProfilePhoto.objects.filter(profile=profile).exists(),
    })


@require_POST
@api_login_required
def upload_profile(request):
    """Multipart form with a `file` field (DOCX or TXT). Stores the parsed resume."""
    upload = request.FILES.get("file")
    if upload is None:
        return JsonResponse({"error": "send the resume in a form field named file"}, status=400)
    if upload.size > extract.MAX_UPLOAD_BYTES:
        return JsonResponse({"error": "the file is too large (limit 2 MB)"}, status=413)
    try:
        text = extract.extract_text(upload.name, upload.read())
    except extract.ExtractError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except extract.OcrBusy as exc:
        return JsonResponse({"error": str(exc)}, status=503)
    if not text:
        return JsonResponse({"error": "no text found in the file"}, status=400)
    if len(text) > settings.MAX_TEXT_CHARS:
        return JsonResponse({"error": "the resume text is too long"}, status=413)
    parsed = resume_parser.parse_resume(text)
    profile = Profile.objects.create(
        user=request.user,
        parsed_json=JsonTextMixin.dump(parsed),
        expires_at=timezone.now() + timedelta(days=RETENTION_DAYS),
    )
    # The file itself is not kept; only the parsed text is stored.
    # `ats` tells the user if their own file reads well for a text scanner.
    return JsonResponse({"id": str(profile.id), "parsed": parsed, "ats": ats.check_text(text),
                         "ocr": bool(getattr(text, "ocr", False))}, status=201)
