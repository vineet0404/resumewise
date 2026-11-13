"""Sign up, sign in, sign out. Session cookie for web; same API for the app later."""

import re
import time

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from . import botcheck, security, throttle
from .views import api_login_required, read_json_body

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL = 254
MAX_NAME = 80
MAX_PASSWORD = 128  # long inputs make password hashing slow on purpose; cap them


def _clean_email(value):
    email = value.strip().lower()
    if len(email) > MAX_EMAIL or not EMAIL_RE.match(email):
        return None
    return email


def _client_ip(request):
    """The caller's address. With TRUSTED_PROXIES = 0 (default) only the socket address counts, so a client
    cannot fake it. Behind a load balancer set TRUSTED_PROXIES to the number of proxies in front of Django;
    then the address that many hops from the right of X-Forwarded-For is used (those hops are ours)."""
    remote = request.META.get("REMOTE_ADDR", "unknown")
    hops = int(getattr(settings, "TRUSTED_PROXIES", 0))
    if hops > 0:
        parts = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops][:64]
    return remote


def _user_json(user):
    acc = security.account_of(user)
    return {"id": user.pk, "email": user.email, "name": user.first_name,
            "email_verified": security.is_verified(user), "totp_enabled": bool(acc and acc.totp_enabled),
            "has_password": user.has_usable_password(), "is_staff": bool(user.is_staff)}


def _remember(request, remember):
    # Tick: stay signed in 30 days. Not ticked: signed out when the browser closes.
    request.session.set_expiry(settings.SESSION_REMEMBER_SECONDS if remember else 0)


PENDING_2FA_SECONDS = 5 * 60


def finish_login(request, user, remember=True, verified_email=False):
    """The one place a person becomes signed in, whatever way they proved who they are.
    Returns True when signed in, or False when an authenticator code is still needed."""
    if verified_email:
        security.mark_verified(user)
    acc = security.account_of(user)
    if acc is not None and acc.totp_enabled:
        request.session["pending_2fa"] = {"uid": user.pk, "remember": bool(remember), "t": time.time(), "tries": 0}
        return False
    request.session.pop("pending_2fa", None)
    login(request, user)
    _remember(request, remember)
    return True


def _with_fresh_csrf(request, payload):
    # Django changes the CSRF token on sign-in and sign-out, so hand out the new one.
    return {**payload, "csrf": get_token(request)}


@require_GET
@ensure_csrf_cookie
def csrf(request):
    """Call once before any POST. Send the returned token in the X-CSRFToken header."""
    return JsonResponse({"csrf": get_token(request)})


@require_POST
def register(request):
    data, error = read_json_body(request, ["email", "password"])
    if error:
        return error
    if botcheck.check(data) is not None:
        return botcheck.reject()
    email = _clean_email(data["email"])
    if email is None:
        return JsonResponse({"error": "enter a valid email"}, status=400)
    password = data["password"]
    if len(password) > MAX_PASSWORD:
        return JsonResponse({"error": "password is too long"}, status=400)
    name = " ".join(str(data.get("name") or "").split())
    if len(name) > MAX_NAME:
        return JsonResponse({"error": "name is too long"}, status=400)
    if data.get("accept_terms") is not True:
        return JsonResponse({"error": "please accept the terms and privacy policy"}, status=400)
    User = get_user_model()
    try:
        validate_password(password, user=User(username=email, email=email))
    except ValidationError as exc:
        return JsonResponse({"error": "weak password", "details": list(exc.messages)}, status=400)
    ip = _client_ip(request)
    if throttle.is_blocked("register", ip, limit=throttle.ip_limit(throttle.MAX_FAILURES)):
        return JsonResponse({"error": "too many attempts, try later"}, status=429)
    throttle.record_failure("register", ip)  # counts every attempt: limits sign-up spam
    if throttle.is_blocked("signup-day", ip, limit=throttle.ip_limit(settings.SIGNUPS_PER_IP_PER_DAY), window=24 * 3600):
        return JsonResponse({"error": "too many accounts from this network today; try tomorrow"}, status=429)
    try:
        user = User.objects.create_user(username=email, email=email, password=password, first_name=name)
    except IntegrityError:
        return JsonResponse({"error": "could not create account"}, status=400)
    throttle.count("signup-day", ip, window=24 * 3600)  # only real new accounts count towards the daily cap
    from .models import Account
    Account.objects.create(user=user)  # email not verified yet
    security.send_verify_email(request, user)
    login(request, user)
    _remember(request, True)
    return JsonResponse(_with_fresh_csrf(request, _user_json(user)), status=201)


@require_POST
def login_view(request):
    data, error = read_json_body(request, ["email", "password"])
    if error:
        return error
    email = data["email"].strip().lower()
    ip = _client_ip(request)
    if throttle.is_blocked("login-ip", ip, limit=throttle.ip_limit(throttle.MAX_FAILURES)) or throttle.is_blocked("login-email", email):
        return JsonResponse({"error": "too many attempts, try later"}, status=429)
    user = None
    if len(data["password"]) <= MAX_PASSWORD:
        user = authenticate(request, username=email, password=data["password"])
    if user is None:
        throttle.record_failure("login-ip", ip)
        throttle.record_failure("login-email", email)
        # One message for "no such user" and "wrong password".
        return JsonResponse({"error": "wrong email or password"}, status=401)
    throttle.clear("login-email", email)
    if not finish_login(request, user, data.get("remember") is not False):
        return JsonResponse({"needs_2fa": True})
    return JsonResponse(_with_fresh_csrf(request, _user_json(user)))


@require_POST
def logout_view(request):
    logout(request)
    return JsonResponse(_with_fresh_csrf(request, {"status": "signed out"}))


@require_GET
@api_login_required
def me(request):
    return JsonResponse(_user_json(request.user))


@require_POST
def forgot_password(request):
    """Always answers the same, so nobody can use this to find out who has an account."""
    data, error = read_json_body(request, ["email"])
    if error:
        return error
    if botcheck.check(data) is not None:
        return botcheck.reject()
    email = _clean_email(data["email"])
    ip = _client_ip(request)
    if throttle.is_blocked("forgot-ip", ip, limit=throttle.ip_limit(10)):
        return JsonResponse({"error": "too many attempts, try later"}, status=429)
    throttle.record_failure("forgot-ip", ip)
    same = {"status": "If that email has an account, a reset link is on its way."}
    if email is None or throttle.is_blocked("forgot-email", email, limit=3):
        return JsonResponse(same)
    throttle.record_failure("forgot-email", email)  # at most 3 emails per 15 min per address
    user = get_user_model().objects.filter(username=email, is_active=True).first()
    if user is not None:
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        # The token sits after "#", so it never reaches server logs or a Referer header.
        link = request.build_absolute_uri("/") + "#reset=%s.%s" % (uid, token)
        send_mail(
            "Reset your ResumeWise password",
            "Hi %s,\n\nUse this link to choose a new password. It works once, for 1 hour:\n\n%s\n\n"
            "If you did not ask for this, ignore this email. Your password stays the same.\n"
            % (user.first_name or "there", link),
            None, [user.email], fail_silently=True)
    return JsonResponse(same)


@require_POST
def reset_password(request):
    data, error = read_json_body(request, ["uid", "token", "password"])
    if error:
        return error
    ip = _client_ip(request)
    if throttle.is_blocked("reset-ip", ip, limit=throttle.ip_limit(10)):
        return JsonResponse({"error": "too many attempts, try later"}, status=429)
    password = data["password"]
    if len(password) > MAX_PASSWORD:
        return JsonResponse({"error": "password is too long"}, status=400)
    User = get_user_model()
    user = None
    try:
        user = User.objects.filter(pk=force_str(urlsafe_base64_decode(data["uid"]))).first()
    except (ValueError, TypeError, OverflowError):
        user = None
    if user is None or not default_token_generator.check_token(user, data["token"]):
        throttle.record_failure("reset-ip", ip)
        return JsonResponse({"error": "this reset link is invalid or has expired, ask for a new one"}, status=400)
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        return JsonResponse({"error": "weak password", "details": list(exc.messages)}, status=400)
    user.set_password(password)  # changes the token too, so the link cannot be used again
    user.save(update_fields=["password"])
    throttle.clear("login-email", user.username)
    return JsonResponse({"status": "password changed, you can log in now"})
