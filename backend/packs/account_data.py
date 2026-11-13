"""Account hygiene: change password, download my data, delete my account."""

import base64
import json

from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import security, throttle
from .account_security import _second_factor_ok, _too_many
from .auth_views import MAX_PASSWORD
from .models import Job, Profile
from .views import api_login_required, read_json_body


def _notify(user, subject, body):
    send_mail(subject, "Hi %s,\n\n%s\n\nIf this was not you, reset your password right away and contact us.\n"
              % (user.first_name or "there", body), None, [user.email], fail_silently=True)


# ---------------- change or set a password ----------------

@require_POST
@api_login_required
def change_password(request):
    data, error = read_json_body(request, ["new"])
    if error:
        return error
    user, new = request.user, data["new"]
    if len(new) > MAX_PASSWORD:
        return JsonResponse({"error": "password is too long"}, status=400)
    had_password = user.has_usable_password()
    if had_password:
        if throttle.is_blocked("pw-change", user.pk, limit=5):
            return _too_many()
        current = data.get("current")
        if not isinstance(current, str) or not user.check_password(current):
            throttle.record_failure("pw-change", user.pk)
            return JsonResponse({"error": "your current password is not right"}, status=400)
        if current == new:
            return JsonResponse({"error": "choose a password different from the current one"}, status=400)
    try:
        validate_password(new, user=user)
    except ValidationError as exc:
        return JsonResponse({"error": "weak password", "details": list(exc.messages)}, status=400)
    user.set_password(new)
    user.save(update_fields=["password"])
    update_session_auth_hash(request, user)  # this browser stays signed in; every other session is signed out
    throttle.clear("pw-change", user.pk)
    _notify(user, "Your ResumeWise password was changed",
            "Your password was %s just now. Other devices were signed out." % ("changed" if had_password else "set"))
    return JsonResponse({"status": "password changed" if had_password else "password set", "has_password": True})


# ---------------- download my data ----------------

def _iso(value):
    return value.isoformat() if value else None


def _loads(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


@require_GET
@api_login_required
def export_data(request):
    user = request.user
    if throttle.is_blocked("export", user.pk, limit=5):
        return _too_many()
    throttle.record_failure("export", user.pk)  # at most 5 downloads per 15 minutes
    acc = security.account_of(user)
    out = {
        "about": "Everything ResumeWise stores about you. Passwords, 2-step secrets and recovery codes are never included.",
        "generated_at": _iso(timezone.now()),
        "account": {
            "email": user.email, "name": user.first_name, "joined": _iso(user.date_joined),
            "email_confirmed": security.is_verified(user), "has_password": user.has_usable_password(),
            "two_step_on": bool(acc and acc.totp_enabled),
            "passkeys": [{"name": p.name, "added": _iso(p.created_at), "last_used": _iso(p.last_used_at)}
                         for p in user.passkeys.order_by("created_at")],
        },
        "cvs": [], "jobs": [],
        "payments": [{"date": _iso(p.created_at), "plan": p.plan_key, "days": p.days, "amount_rupees": p.amount_paise / 100.0,
                      "status": p.status, "razorpay_payment_id": p.payment_id} for p in user.payments.order_by("created_at")],
        "pro_until": _iso(security.account_of(user).pro_until) if security.account_of(user) else None,
        "feedback_sent": [{"sent": _iso(f.created_at), "kind": f.kind, "message": f.message}
                          for f in user.feedback.order_by("created_at")],
    }
    for p in Profile.objects.filter(user=user).order_by("created_at"):
        cv = {"id": str(p.id), "created": _iso(p.created_at), "deletes_on": _iso(p.expires_at),
              "template": p.template_key, "content": _loads(p.parsed_json),
              "earlier_versions": [{"saved": _iso(v.created_at), "reason": v.reason, "content": _loads(v.parsed_json)}
                                   for v in p.versions.order_by("created_at")],
              "photo": None, "tailoring_runs": []}
        photo = getattr(p, "photo", None) if hasattr(p, "photo") else None
        if photo is not None:
            cv["photo"] = {"content_type": photo.content_type, "base64": base64.b64encode(bytes(photo.data)).decode()}
        for run in p.runs.select_related("job").order_by("started_at"):
            outputs = []
            for o in run.outputs.all():
                outputs.append({"kind": o.kind, "content": _loads(o.content_json), "checked": _iso(o.verified_at),
                                "lines": [{"line": c.line_ref, "label": c.label, "from_cv_line": c.source_id,
                                           "your_decision": c.user_ack, "note": c.reason} for c in o.claims.all()]})
            cv["tailoring_runs"].append({"id": str(run.id), "job_id": str(run.job_id), "status": run.status,
                                         "match_score": run.match_score, "ats_score": run.ats_score,
                                         "cost_paise": run.cost_paise, "started": _iso(run.started_at),
                                         "finished": _iso(run.finished_at), "outputs": outputs})
        out["cvs"].append(cv)
    for j in Job.objects.filter(user=user).order_by("created_at"):
        out["jobs"].append({"id": str(j.id), "title": j.title, "company": j.company, "text": j.raw_text,
                            "requirements": _loads(j.requirements_json), "link": j.url, "status": j.status,
                            "notes": j.notes, "match_score": j.score, "interview_answers": _loads(j.answers_json),
                            "applied_on": j.applied_on.isoformat() if j.applied_on else None,
                            "follow_up_on": j.follow_up_on.isoformat() if j.follow_up_on else None,
                            "reminder_email_on": j.remind_email, "created": _iso(j.created_at),
                            "deletes_on": _iso(j.expires_at)})
    resp = JsonResponse(out, json_dumps_params={"indent": 2, "ensure_ascii": False})
    resp["Content-Disposition"] = 'attachment; filename="resumewise-my-data.json"'
    resp["Cache-Control"] = "no-store"
    return resp


# ---------------- delete my account ----------------

@require_POST
@api_login_required
def delete_account(request):
    """Needs the email typed again, plus the password and/or a 2-step code when the account has them."""
    data, error = read_json_body(request, ["confirm_email"])
    if error:
        return error
    user = request.user
    if throttle.is_blocked("delete-acct", user.pk, limit=5):
        return _too_many()

    def refuse(message):
        throttle.record_failure("delete-acct", user.pk)
        return JsonResponse({"error": message}, status=400)

    if data["confirm_email"].strip().lower() != user.email.lower():
        return refuse("type your email address exactly to confirm")
    if user.has_usable_password():
        password = data.get("password")
        if not isinstance(password, str) or not user.check_password(password):
            return refuse("your password is not right")
    acc = security.account_of(user)
    if acc is not None and acc.totp_enabled and not _second_factor_ok(acc, data.get("code")):
        return refuse("that 2-step code is not right")
    email, name = user.email, user.first_name
    send_mail("Your ResumeWise account was deleted",
              "Hi %s,\n\nYour ResumeWise account and everything in it (CVs, jobs, tailoring runs, photos, passkeys) "
              "has been permanently deleted.\n\nIf this was not you, contact us right away.\n" % (name or "there"),
              None, [email], fail_silently=True)
    logout(request)
    user.delete()  # every table that belongs to the user is removed with it
    return JsonResponse({"status": "account deleted"})
