"""Change a saved profile (CV): contact details, add / edit / remove lines, undo."""

from datetime import timedelta

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core import bullets, profile_edit

from .models import JsonTextMixin, Profile, ProfileVersion
from .views import RETENTION_DAYS, api_login_required, read_json_body

MAX_VERSIONS = 20


def _own_profile(request, profile_id):
    """The signed-in user's profile, locked for this change; None if not theirs."""
    return Profile.objects.select_for_update().filter(id=profile_id, user=request.user).first()


def _not_found():
    return JsonResponse({"error": "not found"}, status=404)


def _apply(profile, new_parsed, reason):
    """Save the old CV as a version, store the new one, keep only the latest versions."""
    ProfileVersion.objects.create(profile=profile, parsed_json=profile.parsed_json, reason=reason)
    profile.parsed_json = JsonTextMixin.dump(new_parsed)
    profile.expires_at = timezone.now() + timedelta(days=RETENTION_DAYS)  # active CVs stay longer
    profile.save(update_fields=["parsed_json", "expires_at"])
    old = list(profile.versions.order_by("-created_at").values_list("id", flat=True)[MAX_VERSIONS:])
    if old:
        ProfileVersion.objects.filter(id__in=old).delete()


def _current(profile):
    return profile_edit.with_contact(profile.parsed)


@require_http_methods(["PATCH"])
@api_login_required
@transaction.atomic
def edit_contact(request, profile_id):
    data, error = read_json_body(request, [])
    if error:
        return error
    profile = _own_profile(request, profile_id)
    if profile is None:
        return _not_found()
    try:
        new = profile_edit.set_contact(
            profile.parsed, email=data.get("email"), phone=data.get("phone"), links=data.get("links"),
            location=data.get("location"), name=data.get("name")
        )
    except profile_edit.EditError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    _apply(profile, new, "contact changed")
    return JsonResponse({"id": str(profile.id), "contact": new["contact"]})


@require_http_methods(["POST"])
@api_login_required
@transaction.atomic
def add_item(request, profile_id):
    data, error = read_json_body(request, ["section", "text"])
    if error:
        return error
    profile = _own_profile(request, profile_id)
    if profile is None:
        return _not_found()
    try:
        new, item_id = profile_edit.add_item(_current(profile), data["section"], data["text"])
    except profile_edit.EditError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    _apply(profile, new, "line added")
    return JsonResponse({"id": str(profile.id), "item_id": item_id, "parsed": new}, status=201)


@require_http_methods(["PATCH", "DELETE"])
@api_login_required
@transaction.atomic
def change_item(request, profile_id, item_id):
    profile = _own_profile(request, profile_id)
    if profile is None:
        return _not_found()
    try:
        if request.method == "PATCH":
            data, error = read_json_body(request, ["text"])
            if error:
                return error
            new = profile_edit.edit_item(_current(profile), item_id, data["text"])
            reason = "line edited"
        else:
            new = profile_edit.remove_item(_current(profile), item_id)
            reason = "line removed"
    except profile_edit.EditError as exc:
        status = 404 if "does not exist" in str(exc) else 400
        return JsonResponse({"error": str(exc)}, status=status)
    _apply(profile, new, reason)
    return JsonResponse({"id": str(profile.id), "parsed": new})


@require_http_methods(["GET"])
@api_login_required
def list_versions(request, profile_id):
    profile = Profile.objects.filter(id=profile_id, user=request.user).first()
    if profile is None:
        return _not_found()
    versions = profile.versions.order_by("-created_at")[:MAX_VERSIONS]
    return JsonResponse({
        "versions": [
            {"id": str(v.id), "reason": v.reason, "created_at": v.created_at.isoformat()} for v in versions
        ]
    })


@require_http_methods(["POST"])
@api_login_required
@transaction.atomic
def restore_version(request, profile_id, version_id):
    profile = _own_profile(request, profile_id)
    if profile is None:
        return _not_found()
    version = profile.versions.filter(id=version_id).first()
    if version is None:
        return _not_found()
    restored = JsonTextMixin.load(version.parsed_json)
    _apply(profile, restored, "restored an older version")
    return JsonResponse({"id": str(profile.id), "parsed": profile_edit.with_contact(restored)})


@require_http_methods(["GET"])
@api_login_required
def review(request, profile_id):
    """Tips for every line of the CV (core/bullets.py). Read only."""
    profile = Profile.objects.filter(id=profile_id, user=request.user).first()
    if profile is None:
        return _not_found()
    return JsonResponse(bullets.review(profile.parsed))


@require_http_methods(["POST"])
@api_login_required
def check_line(request):
    """Tips for one line while the person types it."""
    data, error = read_json_body(request, ["text"])
    if error:
        return error
    text = data["text"]
    if not isinstance(text, str) or len(text) > 1000:
        return JsonResponse({"error": "text must be at most 1000 characters"}, status=400)
    section = data.get("section") if data.get("section") in ("experience", "projects", "achievements", "summary") else "experience"
    return JsonResponse({"tips": bullets.check_line(text, section)})
