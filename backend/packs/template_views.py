"""Resume templates and the profile photo."""

from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from core import ats, docx_export, image_check, render

from .models import Profile, ProfilePhoto
from .views import api_login_required, read_json_body


def _not_found():
    return JsonResponse({"error": "not found"}, status=404)


@require_http_methods(["GET"])
@api_login_required
def templates(request):
    return JsonResponse({"templates": render.list_templates(), "default": render.DEFAULT_TEMPLATE})


@require_http_methods(["PATCH"])
@api_login_required
@transaction.atomic
def choose_template(request, profile_id):
    data, error = read_json_body(request, ["template"])
    if error:
        return error
    if data["template"] not in render.TEMPLATES:
        return JsonResponse({"error": "unknown template"}, status=400)
    profile = Profile.objects.select_for_update().filter(id=profile_id, user=request.user).first()
    if profile is None:
        return _not_found()
    profile.template_key = data["template"]
    profile.save(update_fields=["template_key"])
    return JsonResponse({"id": str(profile.id), "template": profile.template_key})


@require_http_methods(["POST", "DELETE"])
@api_login_required
@transaction.atomic
def photo(request, profile_id):
    profile = Profile.objects.select_for_update().filter(id=profile_id, user=request.user).first()
    if profile is None:
        return _not_found()
    if request.method == "DELETE":
        ProfilePhoto.objects.filter(profile=profile).delete()
        return JsonResponse({"id": str(profile.id), "has_photo": False})
    upload = request.FILES.get("photo")
    if upload is None:
        return JsonResponse({"error": "send the photo in a form field named photo"}, status=400)
    if upload.size > image_check.MAX_IMAGE_BYTES:
        return JsonResponse({"error": "the photo is too large (limit 1 MB)"}, status=413)
    try:
        cleaned = image_check.inspect_image(upload.read())
    except image_check.ImageError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    ProfilePhoto.objects.update_or_create(
        profile=profile,
        defaults={"content_type": cleaned["content_type"], "data": cleaned["data"]},
    )
    return JsonResponse({"id": str(profile.id), "has_photo": True,
                         "width": cleaned["width"], "height": cleaned["height"]}, status=201)


@require_http_methods(["GET"])
@api_login_required
def render_profile(request, profile_id):
    profile = Profile.objects.filter(id=profile_id, user=request.user).first()
    if profile is None:
        return _not_found()
    template = request.GET.get("template") or profile.template_key
    if template not in render.TEMPLATES:
        return JsonResponse({"error": "unknown template"}, status=400)
    photo_row = ProfilePhoto.objects.filter(profile=profile).first()
    return render_response(profile.parsed, template, photo_row)


def render_response(parsed, template, photo_row):
    """The finished resume as a locked-down HTML page (no scripts, nothing loaded from outside)."""
    photo_data = None
    if photo_row is not None and render.TEMPLATES[template]["photo"]:
        photo_data = {"content_type": photo_row.content_type, "data": bytes(photo_row.data)}
    page = render.render_resume_html(parsed, template, photo_data)
    response = HttpResponse(page, content_type="text/html; charset=utf-8")
    response["Content-Security-Policy"] = (
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; frame-ancestors 'self'"
    )
    response["X-Frame-Options"] = "SAMEORIGIN"
    response["Cache-Control"] = "private, no-store"
    return response


@require_http_methods(["GET"])
@api_login_required
def ats_check(request, profile_id):
    """How well a plain text scanner can read this CV in the chosen template."""
    profile = Profile.objects.filter(id=profile_id, user=request.user).first()
    if profile is None:
        return _not_found()
    template = request.GET.get("template") or profile.template_key
    if template not in render.TEMPLATES:
        return JsonResponse({"error": "unknown template"}, status=400)
    photo_row = ProfilePhoto.objects.filter(profile=profile).first()
    photo_data = None
    if photo_row is not None and render.TEMPLATES[template]["photo"]:
        photo_data = {"content_type": photo_row.content_type, "data": bytes(photo_row.data)}
    result = ats.check_resume(profile.parsed, template, photo_data)
    result["id"] = str(profile.id)
    result["note"] = "This checks how a simple text scanner reads your CV. It is not a real company's system."
    return JsonResponse(result)


@require_http_methods(["GET"])
@api_login_required
def export_profile(request, profile_id):
    """Download the CV as a Word file (one column, no photo, made by our own code)."""
    profile = Profile.objects.filter(id=profile_id, user=request.user).first()
    if profile is None:
        return _not_found()
    if request.GET.get("format", "docx") != "docx":
        return JsonResponse({"error": "only format=docx; for PDF print the render page"}, status=400)
    response = HttpResponse(
        docx_export.build_docx(profile.parsed),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    response["Content-Disposition"] = 'attachment; filename="resume.docx"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
