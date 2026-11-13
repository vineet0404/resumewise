"""Email verification, magic-link login and authenticator-app two-factor."""

import json
import time

from django.contrib.auth import get_user_model, login
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from . import botcheck, qr, security, throttle, totp
from .auth_views import (PENDING_2FA_SECONDS, _clean_email, _client_ip, _remember, _user_json,
                         _with_fresh_csrf, finish_login)
from .views import api_login_required, read_json_body

SAME_MAGIC = {"status": "If that email has an account, a login link is on its way. It works once, for 15 minutes."}


def _too_many():
    return JsonResponse({"error": "too many attempts, try later"}, status=429)


# ---------------- verify email ----------------

@require_POST
@api_login_required
def verify_send(request):
    if security.is_verified(request.user):
        return JsonResponse({"status": "your email is already confirmed"})
    if throttle.is_blocked("verify-send", request.user.pk, limit=3):
        return _too_many()
    throttle.record_failure("verify-send", request.user.pk)
    security.send_verify_email(request, request.user)
    return JsonResponse({"status": "confirmation email sent"})


@require_POST
def verify_confirm(request):
    data, error = read_json_body(request, ["token"])
    if error:
        return error
    ip = _client_ip(request)
    if throttle.is_blocked("token-ip", ip, limit=throttle.ip_limit(20)):
        return _too_many()
    user = security.consume_token(data["token"], "verify")
    if user is None:
        throttle.record_failure("token-ip", ip)
        return JsonResponse({"error": "this link is invalid or has expired, ask for a new one"}, status=400)
    security.mark_verified(user)
    return JsonResponse({"status": "email confirmed"})


# ---------------- magic link ----------------

@require_POST
def magic_send(request):
    """Same answer whether or not the email has an account."""
    data, error = read_json_body(request, ["email"])
    if error:
        return error
    if botcheck.check(data) is not None:
        return botcheck.reject()
    email = _clean_email(data["email"])
    ip = _client_ip(request)
    if throttle.is_blocked("magic-ip", ip, limit=throttle.ip_limit(10)):
        return _too_many()
    throttle.record_failure("magic-ip", ip)
    if email is None or throttle.is_blocked("magic-email", email, limit=3):
        return JsonResponse(SAME_MAGIC)
    throttle.record_failure("magic-email", email)
    user = get_user_model().objects.filter(username=email, is_active=True).first()
    if user is not None:
        security.send_magic_email(request, user)
    return JsonResponse(SAME_MAGIC)


@require_POST
def magic_login(request):
    data, error = read_json_body(request, ["token"])
    if error:
        return error
    ip = _client_ip(request)
    if throttle.is_blocked("token-ip", ip, limit=throttle.ip_limit(20)):
        return _too_many()
    user = security.consume_token(data["token"], "magic")
    if user is None:
        throttle.record_failure("token-ip", ip)
        return JsonResponse({"error": "this login link is invalid or has expired, ask for a new one"}, status=400)
    if not finish_login(request, user, True, verified_email=True):  # the link proves the inbox is theirs
        return JsonResponse({"needs_2fa": True})
    return JsonResponse(_with_fresh_csrf(request, _user_json(user)))


# ---------------- authenticator app (2FA) ----------------

def _second_factor_ok(acc, code):
    """True if code is a current authenticator code or an unused recovery code (which is then used up)."""
    code = str(code or "")
    secret = security.unseal(acc.totp_secret) if acc.totp_secret else None
    if secret:
        step = totp.check(secret, code, last_step=acc.totp_last_step)
        if step is not None:
            acc.totp_last_step = step
            acc.save(update_fields=["totp_last_step"])
            return True
    hashes = security.load_recovery(acc)
    digest = security.hash_recovery(code)
    if len(code.strip()) >= 8 and digest in hashes:
        hashes.remove(digest)
        acc.recovery_json = json.dumps(hashes)
        acc.save(update_fields=["recovery_json"])
        return True
    return False


@require_POST
@api_login_required
def twofa_setup(request):
    acc = security.ensure_account(request.user)
    if acc.totp_enabled:
        return JsonResponse({"error": "two-factor is already on"}, status=400)
    secret = totp.new_secret()
    acc.totp_secret = security.seal(secret)
    acc.save(update_fields=["totp_secret"])
    uri = totp.otpauth_uri(secret, request.user.email)
    return JsonResponse({"secret": secret, "uri": uri, "qr": qr.encode(uri)})


@require_POST
@api_login_required
def twofa_enable(request):
    data, error = read_json_body(request, ["code"])
    if error:
        return error
    acc = security.ensure_account(request.user)
    if throttle.is_blocked("2fa-setup", request.user.pk, limit=10):
        return _too_many()
    secret = security.unseal(acc.totp_secret) if acc.totp_secret else None
    if acc.totp_enabled or not secret:
        return JsonResponse({"error": "start the setup first"}, status=400)
    step = totp.check(secret, data["code"], last_step=acc.totp_last_step)
    if step is None:
        throttle.record_failure("2fa-setup", request.user.pk)
        return JsonResponse({"error": "that code is not right, check the clock on your phone and try the next code"}, status=400)
    codes = security.new_recovery_codes()
    acc.totp_enabled, acc.totp_last_step = True, step
    acc.recovery_json = json.dumps([security.hash_recovery(c) for c in codes])
    acc.save(update_fields=["totp_enabled", "totp_last_step", "recovery_json"])
    return JsonResponse({"recovery_codes": codes})  # shown once; only hashes are kept


@require_POST
@api_login_required
def twofa_disable(request):
    data, error = read_json_body(request, ["code"])
    if error:
        return error
    acc = security.account_of(request.user)
    if acc is None or not acc.totp_enabled:
        return JsonResponse({"error": "two-factor is not on"}, status=400)
    if throttle.is_blocked("2fa-off", request.user.pk, limit=10):
        return _too_many()
    if not _second_factor_ok(acc, data["code"]):
        throttle.record_failure("2fa-off", request.user.pk)
        return JsonResponse({"error": "that code is not right"}, status=400)
    acc.totp_enabled, acc.totp_secret, acc.recovery_json, acc.totp_last_step = False, "", "", 0
    acc.save()
    return JsonResponse({"status": "two-factor is off"})


@require_POST
@api_login_required
def twofa_new_recovery_codes(request):
    data, error = read_json_body(request, ["code"])
    if error:
        return error
    acc = security.account_of(request.user)
    if acc is None or not acc.totp_enabled:
        return JsonResponse({"error": "two-factor is not on"}, status=400)
    if throttle.is_blocked("2fa-off", request.user.pk, limit=10):
        return _too_many()
    if not _second_factor_ok(acc, data["code"]):
        throttle.record_failure("2fa-off", request.user.pk)
        return JsonResponse({"error": "that code is not right"}, status=400)
    codes = security.new_recovery_codes()
    acc.recovery_json = json.dumps([security.hash_recovery(c) for c in codes])
    acc.save(update_fields=["recovery_json"])
    return JsonResponse({"recovery_codes": codes})


@require_POST
def twofa_verify(request):
    """Second step of sign-in, after the password (or link, or Google) was accepted."""
    data, error = read_json_body(request, ["code"])
    if error:
        return error
    pending = request.session.get("pending_2fa")
    if not pending or time.time() - pending["t"] > PENDING_2FA_SECONDS:
        request.session.pop("pending_2fa", None)
        return JsonResponse({"error": "your sign-in took too long, please log in again"}, status=400)
    user = get_user_model().objects.filter(pk=pending["uid"], is_active=True).first()
    acc = security.account_of(user) if user else None
    if acc is None or not acc.totp_enabled:
        request.session.pop("pending_2fa", None)
        return JsonResponse({"error": "please log in again"}, status=400)
    if pending["tries"] >= 5 or throttle.is_blocked("2fa-login", user.pk, limit=10):
        request.session.pop("pending_2fa", None)
        return _too_many()
    if not _second_factor_ok(acc, data["code"]):
        pending["tries"] += 1
        request.session["pending_2fa"] = pending
        throttle.record_failure("2fa-login", user.pk)
        return JsonResponse({"error": "that code is not right"}, status=401)
    request.session.pop("pending_2fa", None)
    throttle.clear("2fa-login", user.pk)
    login(request, user)
    _remember(request, pending["remember"])
    return JsonResponse(_with_fresh_csrf(request, _user_json(user)))
