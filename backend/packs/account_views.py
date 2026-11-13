"""What a signed-in user needs to find and manage their own data: list, open, delete."""

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from core import profile_edit

from . import views
from .models import Job, Profile
from .views import api_login_required

LIST_LIMIT = 20


@require_http_methods(["GET", "POST"])
@api_login_required
def profiles_collection(request):
    """GET: my CVs, newest first. POST: create one from pasted text (see views.create_profile)."""
    if request.method == "POST":
        return views.create_profile(request)
    rows = Profile.objects.filter(user=request.user).order_by("-created_at")[:LIST_LIMIT]
    return JsonResponse({"profiles": [
        {"id": str(p.id), "name": profile_edit.name_and_role(p.parsed)[0], "template": p.template_key,
         "created_at": p.created_at.isoformat()} for p in rows]})


@require_http_methods(["GET", "DELETE"])
@api_login_required
def profile_item(request, profile_id):
    """GET: one of my CVs. DELETE: remove it with its versions, photo, runs and job texts."""
    if request.method == "GET":
        return views.get_profile(request, profile_id)
    with transaction.atomic():
        profile = Profile.objects.select_for_update().filter(id=profile_id, user=request.user).first()
        if profile is None:
            return JsonResponse({"error": "not found"}, status=404)
        job_ids = list(profile.runs.values_list("job_id", flat=True))
        profile.delete()
        Job.objects.filter(id__in=job_ids, user=request.user, runs__isnull=True).delete()
    return JsonResponse({"status": "deleted"})


@require_http_methods(["GET"])
@api_login_required
def profile_runs(request, profile_id):
    profile = Profile.objects.filter(id=profile_id, user=request.user).first()
    if profile is None:
        return JsonResponse({"error": "not found"}, status=404)
    runs = profile.runs.select_related("job").order_by("-started_at")[:LIST_LIMIT]
    return JsonResponse({"runs": [
        {"id": str(r.id), "status": r.status, "job_title": r.job.title, "created_at": r.started_at.isoformat()}
        for r in runs]})
