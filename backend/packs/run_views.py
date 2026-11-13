"""Review and export a tailored CV: the user decides on every new line, then exports."""

from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from core import ats, docx_export, render, tailored_cv

from .models import Claim, JsonTextMixin, ProfilePhoto, Run
from .template_views import render_response
from .views import api_login_required, read_json_body

DECISIONS = ("confirmed", "removed", "pending")


def _own_run(request, run_id):
    return Run.objects.select_related("profile").filter(id=run_id, profile__user=request.user).first()


def _not_found():
    return JsonResponse({"error": "not found"}, status=404)


def _state(run):
    output = run.outputs.filter(kind="resume").first()
    content = JsonTextMixin.load(output.content_json)
    claims = list(output.claims.all())
    by_ref = {c.line_ref: c for c in claims}
    decisions = {c.line_ref: c.user_ack for c in claims}
    plain = [{"line_ref": c.line_ref, "label": c.label} for c in claims]
    lines = []
    for si, section in enumerate(content["sections"]):
        for bi, bullet in enumerate(section["bullets"]):
            ref = "s%d.b%d" % (si, bi)
            claim = by_ref.get(ref)
            lines.append({
                "line_ref": ref, "section": section["type"], "text": bullet["text"],
                "label": claim.label if claim else "new", "reason": claim.reason if claim else "",
                "source_id": claim.source_id if claim else "", "decision": decisions.get(ref, "pending"),
            })
    pending = tailored_cv.pending_new(plain, decisions)
    return output, content, decisions, lines, pending


@require_http_methods(["GET"])
@api_login_required
def run_detail(request, run_id):
    run = _own_run(request, run_id)
    if run is None:
        return _not_found()
    _, content, _, lines, pending = _state(run)
    return JsonResponse({"id": str(run.id), "status": run.status, "lines": lines, "gaps": content.get("gaps", []),
                         "pending": pending, "can_export": not pending})


@require_http_methods(["PATCH"])
@api_login_required
@transaction.atomic
def decide(request, run_id, line_ref):
    data, error = read_json_body(request, ["decision"])
    if error:
        return error
    if data["decision"] not in DECISIONS:
        return JsonResponse({"error": "decision must be one of: " + ", ".join(DECISIONS)}, status=400)
    run = _own_run(request, run_id)
    if run is None:
        return _not_found()
    claim = Claim.objects.filter(output__run=run, line_ref=line_ref).first()
    if claim is None:
        return _not_found()
    claim.user_ack = data["decision"]
    claim.save(update_fields=["user_ack"])
    _, _, _, lines, pending = _state(run)
    run.status = "ready" if not pending else "needs_review"
    run.save(update_fields=["status"])
    return JsonResponse({"line_ref": line_ref, "decision": claim.user_ack, "pending": pending,
                         "can_export": not pending})


def _tailored(run):
    output, content, decisions, _, pending = _state(run)
    if pending:
        return None, JsonResponse({"error": "%d new line(s) need your decision first" % len(pending),
                                   "pending": pending}, status=409)
    return tailored_cv.build_resume(run.profile.parsed, content, decisions), None


@require_http_methods(["GET"])
@api_login_required
def run_render(request, run_id):
    run = _own_run(request, run_id)
    if run is None:
        return _not_found()
    resume, blocked = _tailored(run)
    if blocked:
        return blocked
    template = request.GET.get("template") or run.profile.template_key
    if template not in render.TEMPLATES:
        return JsonResponse({"error": "unknown template"}, status=400)
    return render_response(resume, template, ProfilePhoto.objects.filter(profile=run.profile).first())


@require_http_methods(["GET"])
@api_login_required
def run_ats(request, run_id):
    run = _own_run(request, run_id)
    if run is None:
        return _not_found()
    resume, blocked = _tailored(run)
    if blocked:
        return blocked
    template = request.GET.get("template") or run.profile.template_key
    if template not in render.TEMPLATES:
        return JsonResponse({"error": "unknown template"}, status=400)
    report = ats.check_resume(resume, template)
    report["note"] = "This checks how a simple text scanner reads your CV. It is not a real company's system."
    return JsonResponse(report)


@require_http_methods(["GET"])
@api_login_required
def run_export(request, run_id):
    run = _own_run(request, run_id)
    if run is None:
        return _not_found()
    if request.GET.get("format", "docx") != "docx":
        return JsonResponse({"error": "only format=docx; for PDF print the render page"}, status=400)
    resume, blocked = _tailored(run)
    if blocked:
        return blocked
    response = HttpResponse(
        docx_export.build_docx(resume),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    response["Content-Disposition"] = 'attachment; filename="tailored-resume.docx"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
