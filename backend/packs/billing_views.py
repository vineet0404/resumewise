"""Plan status, buying a plan (Razorpay Payment Link), the page Razorpay sends people back to, and the webhook."""

import json
import logging
from datetime import timedelta

from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import billing, security
from .models import Job, Payment, Run
from .views import api_login_required, read_json_body

log = logging.getLogger("billing")
CHECKOUTS_PER_HOUR = 5


def _plans():
    return [{"key": k, "label": v["label"], "days": v["days"], "price_rupees": v["price_paise"] / 100.0}
            for k, v in settings.PLANS.items()]


@require_GET
@api_login_required
def status(request):
    user = request.user
    limits = billing.limits_for(user)
    since = timezone.now() - timedelta(hours=24)
    until = billing.pro_until(user)
    return JsonResponse({
        "enabled": billing.enabled(), "plan": limits["plan"],
        "pro_until": until.isoformat() if until and until > timezone.now() else None,
        "limits": {"ai_per_day": limits["ai_per_day"], "max_jobs": limits["max_jobs"]},
        "usage": {"ai_today": Run.objects.filter(profile__user=user, started_at__gte=since).count(),
                  "jobs": Job.objects.filter(user=user).count()},
        "plans": _plans(),
        "payments": [{"date": p.created_at.date().isoformat(), "plan": p.plan_key, "amount_rupees": p.amount_paise / 100.0, "status": p.status}
                     for p in Payment.objects.filter(user=user).order_by("-created_at")[:10]],
    })


@require_POST
@api_login_required
def checkout(request):
    if not billing.enabled():
        return JsonResponse({"error": "payments are not open yet"}, status=503)
    data, error = read_json_body(request, ["plan"])
    if error:
        return error
    if data["plan"] not in settings.PLANS:
        return JsonResponse({"error": "unknown plan"}, status=400)
    if not security.is_verified(request.user):
        return JsonResponse({"error": "please confirm your email first (check your inbox)", "code": "email_not_verified"}, status=403)
    since = timezone.now() - timedelta(hours=1)
    if Payment.objects.filter(user=request.user, created_at__gte=since).count() >= CHECKOUTS_PER_HOUR:
        return JsonResponse({"error": "too many attempts; try again in an hour"}, status=429)
    try:
        payment = billing.start_checkout(request.user, data["plan"])
    except billing.BillingError as exc:
        log.warning("checkout failed: %s", exc)
        return JsonResponse({"error": str(exc)}, status=502)
    return JsonResponse({"url": payment.link_url}, status=201)


@require_GET
def back_from_razorpay(request):
    """Razorpay sends the person here after paying. The signed values decide; the webhook is the backup."""
    params = request.GET
    outcome = "failed"
    if billing.enabled() and billing.return_signature_ok(params):
        payment = Payment.objects.filter(reference=params.get("razorpay_payment_link_reference_id", ""),
                                         link_id=params.get("razorpay_payment_link_id", "")).first()
        if payment is not None:
            if params.get("razorpay_payment_link_status") == "paid":
                billing.grant(payment.pk, params.get("razorpay_payment_id", ""))
                payment.refresh_from_db()
                outcome = "paid" if payment.status in ("paid", "refunded") else "pending"
            else:
                outcome = "pending"
    return HttpResponseRedirect("/#billing=" + outcome)


@csrf_exempt
@require_http_methods(["POST"])
def webhook(request):
    """Razorpay tells us about payments and refunds. Signed with the webhook secret; anything unsigned is refused."""
    raw = request.body
    if not billing.webhook_enabled() or not billing.webhook_signature_ok(raw, request.META.get("HTTP_X_RAZORPAY_SIGNATURE", "")):
        return JsonResponse({"error": "bad signature"}, status=400)
    try:
        event = json.loads(raw.decode("utf-8"))
        name = event.get("event", "")
        payload = event.get("payload", {})
    except (ValueError, AttributeError):
        return JsonResponse({"error": "bad body"}, status=400)
    try:
        if name == "payment_link.paid":
            link = payload["payment_link"]["entity"]
            pay = payload["payment"]["entity"]
            payment = Payment.objects.filter(reference=link.get("reference_id", ""), link_id=link.get("id", "")).first()
            if payment is None:
                log.warning("webhook for an unknown payment link")
            elif not billing.grant(payment.pk, str(pay.get("id", "")), pay.get("amount")):
                payment.refresh_from_db()
                if payment.status == "created":
                    log.warning("webhook amount did not match payment %s", payment.reference)
        elif name == "refund.processed":
            refund = payload["refund"]["entity"]
            payment = Payment.objects.filter(payment_id=str(refund.get("payment_id", ""))).exclude(payment_id="").first()
            if payment is not None:
                billing.refund(payment)
    except (KeyError, TypeError, ValueError):
        log.warning("webhook event %s had an unexpected shape", name)
    return JsonResponse({"status": "ok"})
