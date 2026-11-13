"""Plans, limits and Razorpay Payment Links, in our own code (no Razorpay library).

Why Payment Links: the person pays on Razorpay's own page, so card and UPI details never touch our server or our
page security rules. We only (1) ask Razorpay to make a link for an amount, (2) check Razorpay's signed answer, and
(3) switch the person's plan on. Every signature is checked with HMAC-SHA256 and a constant-time compare.
"""

import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Account, Payment

LINK_LIFETIME = timedelta(hours=24)


class BillingError(Exception):
    pass


def enabled():
    """Payments are open only when the owner has set the Razorpay keys and the site address."""
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET and settings.SITE_URL)


def webhook_enabled():
    return bool(settings.RAZORPAY_WEBHOOK_SECRET)


# ----- plan and limits -----
def pro_until(user):
    acc = Account.objects.filter(user=user).first()
    return acc.pro_until if acc else None


def is_pro(user):
    until = pro_until(user)
    return bool(until and until > timezone.now())


def limits_for(user):
    """AI runs per day and saved jobs for this person. Until payments are set up, everyone gets the Pro limits."""
    from .job_views import MAX_JOBS
    if not enabled() or is_pro(user):
        return {"ai_per_day": settings.AI_DAILY_PER_USER, "max_jobs": MAX_JOBS, "plan": "pro" if is_pro(user) else "open"}
    return {"ai_per_day": min(settings.FREE_AI_PER_DAY, settings.AI_DAILY_PER_USER), "max_jobs": min(settings.FREE_MAX_JOBS, MAX_JOBS), "plan": "free"}


# ----- signatures -----
def _hmac_hex(secret, message):
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def signature_ok(secret, message, signature):
    if not secret or not isinstance(signature, str) or not signature:
        return False
    return hmac.compare_digest(_hmac_hex(secret, message), signature.strip().lower())


def return_signature_ok(params):
    """The page Razorpay sends the person back to carries a signature over four values."""
    get = lambda k: params.get(k, "")
    message = "|".join([get("razorpay_payment_link_id"), get("razorpay_payment_link_reference_id"),
                        get("razorpay_payment_link_status"), get("razorpay_payment_id")]).encode("utf-8")
    return signature_ok(settings.RAZORPAY_KEY_SECRET, message, get("razorpay_signature"))


def webhook_signature_ok(raw_body, signature):
    return signature_ok(settings.RAZORPAY_WEBHOOK_SECRET, raw_body, signature)


# ----- talking to Razorpay -----
def _api(method, path, body=None):
    token = base64.b64encode(("%s:%s" % (settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)).encode()).decode()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(settings.RAZORPAY_API + path, data=data, method=method)
    req.add_header("Authorization", "Basic " + token)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("description", "")
        except Exception:  # noqa: BLE001
            pass
        raise BillingError("the payment provider refused the request (%s)" % (detail or exc.code))
    except Exception as exc:  # noqa: BLE001
        raise BillingError("could not reach the payment provider: %s" % type(exc).__name__)


def start_checkout(user, plan_key):
    """Create a Payment row and a Razorpay Payment Link; return the Payment (with link_url)."""
    plan = settings.PLANS.get(plan_key)
    if plan is None:
        raise BillingError("unknown plan")
    payment = Payment.objects.create(user=user, reference="rw_" + uuid.uuid4().hex[:24], plan_key=plan_key,
                                     days=plan["days"], amount_paise=plan["price_paise"])
    body = {
        "amount": plan["price_paise"], "currency": "INR", "accept_partial": False,
        "reference_id": payment.reference, "description": "ResumeWise " + plan["label"],
        "customer": {"name": (user.first_name or user.email.split("@")[0])[:50], "email": user.email},
        "notify": {"email": True, "sms": False}, "reminder_enable": False,
        "callback_url": settings.SITE_URL + "/v1/billing/return", "callback_method": "get",
        "expire_by": int((timezone.now() + LINK_LIFETIME).timestamp()),
        "notes": {"plan": plan_key},
    }
    try:
        answer = _api("POST", "/v1/payment_links", body)
        link_id, url = str(answer["id"]), str(answer["short_url"])
    except (BillingError, KeyError, TypeError):
        payment.delete()
        raise
    if not url.startswith("https://") and not settings.DEBUG:
        payment.delete()
        raise BillingError("the payment provider sent an unexpected link")
    payment.link_id, payment.link_url = link_id, url[:300]
    payment.save(update_fields=["link_id", "link_url"])
    return payment


# ----- switching the plan on and off (idempotent: the same payment is never counted twice) -----
def _account(user):
    acc = Account.objects.filter(user=user).first()
    if acc is None:  # an older account: keep it treated as email-confirmed
        acc = Account.objects.create(user=user, email_verified_at=timezone.now())
    return acc


def grant(payment_id_in_db, razorpay_payment_id, paid_paise=None):
    """Mark a payment paid and add its days. Returns True if this call did it, False if it was already done or refused."""
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_id_in_db)
        if payment.status != "created":
            return False
        if paid_paise is not None and int(paid_paise) != payment.amount_paise:
            return False  # the amount Razorpay took is not the amount we asked for: do nothing, look at it by hand
        payment.status, payment.payment_id, payment.paid_at = "paid", razorpay_payment_id[:60], timezone.now()
        payment.save(update_fields=["status", "payment_id", "paid_at"])
        if payment.user_id:
            acc = _account(payment.user)
            start = max(timezone.now(), acc.pro_until or timezone.now())
            acc.pro_until = start + timedelta(days=payment.days)
            acc.save(update_fields=["pro_until"])
        return True


def refund(payment):
    """Razorpay refunded this payment: take its days back (never below now)."""
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status != "paid":
            return False
        payment.status = "refunded"
        payment.save(update_fields=["status"])
        if payment.user_id:
            acc = _account(payment.user)
            if acc.pro_until:
                acc.pro_until = max(timezone.now(), acc.pro_until - timedelta(days=payment.days))
                acc.save(update_fields=["pro_until"])
        return True
