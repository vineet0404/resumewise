"""AI tailoring: the only endpoint that sends text to a hosted model."""

import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import gateway as gw
from core import keywords, providers, tailor_service

from . import billing, security, throttle
from .models import Claim, Job, JsonTextMixin, Output, Profile, Run
from .views import RETENTION_DAYS, api_login_required, read_json_body

log = logging.getLogger(__name__)
MAX_JOB_CHARS = 8000
_AI_SLOTS = threading.BoundedSemaphore(max(1, int(getattr(settings, "AI_MAX_CONCURRENT", 4))))
TAILOR_LIMIT = 10  # runs per user per 15 minutes


def build_gateway():
    """A gateway wired to the hosted provider, or None when no API key is set.

    Tests replace this function with one that returns a gateway with a fake provider.
    """
    provider = providers.provider_from_env()  # may raise GatewayError for a placeholder key
    if provider is None:
        return None
    return gw.Gateway({"tailor": provider})


@require_POST
@api_login_required
def tailor(request, profile_id):
    profile = Profile.objects.filter(id=profile_id, user=request.user).first()
    if profile is None:
        return JsonResponse({"error": "not found"}, status=404)
    if not security.is_verified(request.user):  # AI costs money: only for confirmed emails
        return JsonResponse({"error": "please confirm your email first (check your inbox)", "code": "email_not_verified"}, status=403)
    data, error = read_json_body(request, ["job_text"])
    if error:
        return error
    if len(data["job_text"]) > MAX_JOB_CHARS:
        return JsonResponse({"error": "job_text is too long (limit %d characters)" % MAX_JOB_CHARS}, status=413)
    try:
        gateway = build_gateway()
    except gw.GatewayError as err:
        return JsonResponse({"error": str(err)}, status=503)
    if gateway is None:
        return JsonResponse({"error": "AI is not set up on this server"}, status=503)
    since = timezone.now() - timedelta(hours=24)
    limits = billing.limits_for(request.user)
    if Run.objects.filter(profile__user=request.user, started_at__gte=since).count() >= limits["ai_per_day"]:
        return JsonResponse({"error": "daily limit reached (%d AI runs per day); try again tomorrow" % limits["ai_per_day"] + (" or choose the Pro plan in the Account tab" if limits["plan"] == "free" else ""),
                             "code": "daily_limit", "plan": limits["plan"]}, status=429)
    spent = Run.objects.filter(started_at__gte=since).aggregate(total=Sum("cost_paise"))["total"] or 0
    if spent >= settings.AI_DAILY_BUDGET_PAISE:  # the owner's safety net: all people together
        return JsonResponse({"error": "the AI is resting for today; please try again tomorrow", "code": "budget"}, status=503)
    ident = str(request.user.pk)
    if throttle.is_blocked("tailor", ident, TAILOR_LIMIT):
        return JsonResponse({"error": "too many requests; try again in a few minutes"}, status=429)
    throttle.record_failure("tailor", ident)  # counts every call

    if not _AI_SLOTS.acquire(blocking=False):  # too many AI calls running right now in this process
        response = JsonResponse({"error": "the AI is busy right now; please try again in a minute", "code": "busy"}, status=503)
        response["Retry-After"] = "30"
        return response
    try:
        result = tailor_service.tailor(profile.parsed, data["job_text"], gateway)
    except ValueError as err:
        return JsonResponse({"error": str(err)}, status=400)
    except gw.CostCapExceeded:
        return JsonResponse({"error": "this request cost too much and was stopped"}, status=502)
    except gw.GatewayError as err:
        log.warning("tailoring failed: %s", err)  # message only; never the prompt or the resume
        if "key was rejected" in str(err):
            return JsonResponse({"error": "the AI key was rejected; check ANTHROPIC_API_KEY on the server"}, status=502)
        return JsonResponse({"error": "the AI could not produce a safe result; please try again"}, status=502)

    finally:
        _AI_SLOTS.release()

    run = save_run(request.user, profile, data["job_text"], str(data.get("job_title") or ""), result)
    result["run_id"] = str(run.id)
    return JsonResponse(result, status=201)


def save_run(user, profile, job_text, job_title, result):
    """Store a tailoring result (job, run, output and one claim per line) and return the Run."""
    with transaction.atomic():
        job = Job.objects.create(
            user=user, title=job_title[:200], raw_text=job_text,
            requirements_json=JsonTextMixin.dump(keywords.extract_requirements(job_text)),
            expires_at=timezone.now() + timedelta(days=RETENTION_DAYS),
        )
        run = Run.objects.create(profile=profile, job=job, status="needs_review" if result["needs_review"] else "ready",
                                 cost_paise=result["cost_paise"], finished_at=timezone.now())
        output = Output.objects.create(run=run, kind="resume", content_json=JsonTextMixin.dump(
            {"sections": result["sections"], "gaps": result["gaps"]}))
        Claim.objects.bulk_create([
            Claim(output=output, line_ref=c["line_ref"], label=c["label"], source_id=c["source_id"] or "",
                  reason=c.get("reason", "")[:200])
            for c in result["claims"]])
    return run
