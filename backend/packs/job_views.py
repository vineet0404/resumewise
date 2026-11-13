"""Job tracker: save jobs, see how well the CV matches, write a cover letter, practise the interview.

All of it is our own code (core/job_match.py, cover_letter.py, interview.py): no AI, no cost,
and nothing is invented. Jobs are deleted with the same 30-day rule as CVs.
"""

import json
import uuid
from datetime import date, timedelta

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core import cover_letter, interview, job_match, keywords

from .models import Job, JsonTextMixin, Profile
from .views import RETENTION_DAYS, api_login_required, read_json_body

MAX_JOBS = 100
MAX_JOB_TEXT = 8000
STATUSES = ("saved", "applied", "interview", "offer", "rejected")


def _nf():
    return JsonResponse({"error": "not found"}, status=404)


def _bad(message, status=400):
    return JsonResponse({"error": message}, status=status)


def _own(request, job_id):
    return Job.objects.filter(id=job_id, user=request.user).first()


def _profile(request, value):
    """The signed-in user's CV named by `value` (an id string); None if missing or not theirs."""
    try:
        pid = uuid.UUID(str(value))
    except ValueError:  # a malformed id is the same as "not found"
        return None
    return Profile.objects.filter(id=pid, user=request.user).first()


FOLLOW_UP_DAYS = 7  # default wait after applying before we suggest a follow-up
MAX_FOLLOW_UP_DAYS = 365


def is_due(job, today=None):
    """A job needs a follow-up when it is still at "applied" and its follow-up day has come."""
    today = today or timezone.localdate()
    return job.status == "applied" and job.follow_up_on is not None and job.follow_up_on <= today


def _short(job):
    today = timezone.localdate()
    return {"id": str(job.id), "title": job.title, "company": job.company, "url": job.url, "status": job.status,
            "score": job.score, "created": job.created_at.isoformat(), "updated": job.updated_at.isoformat(),
            "applied_on": job.applied_on.isoformat() if job.applied_on else None,
            "follow_up_on": job.follow_up_on.isoformat() if job.follow_up_on else None,
            "remind_email": job.remind_email, "due": is_due(job, today),
            "days_since_applied": (today - job.applied_on).days if job.applied_on else None}


def _clean_day(value):
    """A day as YYYY-MM-DD, within a year from today. Returns (date or None, error)."""
    if value in (None, ""):
        return None, None
    if not isinstance(value, str):
        return None, "follow-up day must be a date like 2026-12-31"
    try:
        day = date.fromisoformat(value.strip())
    except ValueError:
        return None, "follow-up day must be a date like 2026-12-31"
    today = timezone.localdate()
    if day < today - timedelta(days=1) or day > today + timedelta(days=MAX_FOLLOW_UP_DAYS):
        return None, "follow-up day must be within the next year"
    return day, None


def _clean_url(value):
    if value is None or value == "":
        return "", None
    if not isinstance(value, str):
        return None, "link must be text"
    value = value.strip()
    if len(value) > 500:
        return None, "link is too long"
    if not value.lower().startswith(("http://", "https://")) or " " in value:
        return None, "link must start with http:// or https://"
    return value, None


def _text_field(data, key, limit, label, required=False):
    value = data.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        return None, "%s must be text" % label
    value = value.strip()
    if required and not value:
        return None, "%s is required" % label
    if len(value) > limit:
        return None, "%s is too long (limit %d characters)" % (label, limit)
    return value, None


def _touch(job):
    job.expires_at = timezone.now() + timedelta(days=RETENTION_DAYS)


@require_http_methods(["GET"])
@api_login_required
def jobs_due(request):
    """Jobs that need a follow-up today or earlier (shown as a banner in the Jobs tab)."""
    today = timezone.localdate()
    jobs = Job.objects.filter(user=request.user, status="applied", follow_up_on__lte=today).order_by("follow_up_on")
    return JsonResponse({"jobs": [_short(j) for j in jobs]})


@require_http_methods(["GET", "POST"])
@api_login_required
def jobs_collection(request):
    if request.method == "GET":
        jobs = Job.objects.filter(user=request.user).order_by("-updated_at")
        return JsonResponse({"jobs": [_short(j) for j in jobs]})
    data, error = read_json_body(request, [])
    if error:
        return error
    title, err = _text_field(data, "title", 200, "job title", required=True)
    company, err2 = _text_field(data, "company", 200, "company")
    text, err3 = _text_field(data, "job_text", MAX_JOB_TEXT, "job description", required=True)
    url, err4 = _clean_url(data.get("url"))
    for e in (err, err2, err3, err4):
        if e:
            return _bad(e, 413 if "too long" in e else 400)
    from . import billing
    limits = billing.limits_for(request.user)
    if Job.objects.filter(user=request.user).count() >= limits["max_jobs"]:
        return _bad("you have saved %d jobs; delete some first" % limits["max_jobs"] + (" or choose the Pro plan in the Account tab" if limits["plan"] == "free" else ""), 409)
    job = Job(user=request.user, title=title, company=company, url=url, raw_text=text,
              requirements_json=JsonTextMixin.dump(keywords.extract_requirements(text)))
    _touch(job)
    profile = _profile(request, data.get("profile_id")) if data.get("profile_id") else None
    if profile is not None:
        job.score = job_match.analyse(profile.parsed, text)["score"]
    job.save()
    return JsonResponse(_short(job), status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
@api_login_required
def job_item(request, job_id):
    job = _own(request, job_id)
    if job is None:
        return _nf()
    if request.method == "DELETE":
        job.delete()
        return JsonResponse({"deleted": True})
    if request.method == "GET":
        out = _short(job)
        out.update({"text": job.raw_text, "notes": job.notes, "match": None})
        profile = _profile(request, request.GET.get("profile_id")) if request.GET.get("profile_id") else None
        if profile is not None:
            out["match"] = job_match.analyse(profile.parsed, job.raw_text)
            if job.score != out["match"]["score"]:
                job.score = out["match"]["score"]
                job.save(update_fields=["score", "updated_at"])
                out["score"] = job.score
        return JsonResponse(out)
    data, error = read_json_body(request, [])
    if error:
        return error
    if "status" in data:
        if data["status"] not in STATUSES:
            return _bad("status must be one of: " + ", ".join(STATUSES))
        if data["status"] != job.status:
            job.status = data["status"]
            if job.status == "applied" and job.applied_on is None:
                job.applied_on = timezone.localdate()
                if job.follow_up_on is None:
                    job.follow_up_on = job.applied_on + timedelta(days=FOLLOW_UP_DAYS)
                    job.reminded_at = None
    if "follow_up_on" in data:
        day, e = _clean_day(data["follow_up_on"])
        if e:
            return _bad(e)
        if day != job.follow_up_on:
            job.follow_up_on = day
            job.reminded_at = None  # a new day means a new reminder
    if "remind_email" in data:
        if not isinstance(data["remind_email"], bool):
            return _bad("remind_email must be true or false")
        job.remind_email = data["remind_email"]
    if "notes" in data:
        value, e = _text_field(data, "notes", 4000, "notes")
        if e:
            return _bad(e, 413)
        job.notes = value
    for key, limit, label in (("title", 200, "job title"), ("company", 200, "company")):
        if key in data:
            value, e = _text_field(data, key, limit, label, required=(key == "title"))
            if e:
                return _bad(e, 413 if "too long" in e else 400)
            setattr(job, key, value)
    if "url" in data:
        url, e = _clean_url(data["url"])
        if e:
            return _bad(e)
        job.url = url
    _touch(job)
    job.save()
    return JsonResponse(_short(job))


@require_http_methods(["POST"])
@api_login_required
def cover_letter_view(request, job_id):
    job = _own(request, job_id)
    if job is None:
        return _nf()
    data, error = read_json_body(request, [])
    if error:
        return error
    profile = _profile(request, data.get("profile_id"))
    if profile is None:
        return _bad("choose your CV first")
    why, e1 = _text_field(data, "why", 1200, "your own paragraph")
    manager, e2 = _text_field(data, "manager", 80, "name")
    for e in (e1, e2):
        if e:
            return _bad(e, 413 if "too long" in e else 400)
    parsed = profile.parsed
    result = cover_letter.write(parsed, job_match.analyse(parsed, job.raw_text), job.title, job.company, why, manager)
    return JsonResponse(result)


@require_http_methods(["GET", "PUT"])
@api_login_required
def interview_view(request, job_id):
    job = _own(request, job_id)
    if job is None:
        return _nf()
    source = request.GET if request.method == "GET" else None
    data = {}
    if request.method == "PUT":
        data, error = read_json_body(request, [])
        if error:
            return error
    profile = _profile(request, (source.get("profile_id") if source else data.get("profile_id")) or "")
    if profile is None:
        return _bad("choose your CV first")
    parsed = profile.parsed
    qs = interview.questions(parsed, job_match.analyse(parsed, job.raw_text), job.title, job.company)
    try:
        saved = json.loads(job.answers_json) if job.answers_json else {}
    except ValueError:
        saved = {}
    if request.method == "PUT":
        given = data.get("answers")
        if not isinstance(given, dict):
            return _bad("answers must be an object")
        known = {q["id"] for q in qs}
        for key, value in given.items():
            if key not in known:
                return _bad("unknown question")
            if not isinstance(value, str):
                return _bad("each answer must be text")
            if len(value) > interview.MAX_ANSWER:
                return _bad("an answer is too long (limit %d characters)" % interview.MAX_ANSWER, 413)
        saved.update({k: v.strip() for k, v in given.items()})
        saved = {k: v for k, v in saved.items() if v}
        job.answers_json = json.dumps(saved, ensure_ascii=False)
        _touch(job)
        job.save()
    for q in qs:
        q["answer"] = saved.get(q["id"], "")
    return JsonResponse({"questions": qs})
