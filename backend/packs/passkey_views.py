"""Passkey (WebAuthn) endpoints. The browser talks to the person's device; this server only
issues a one-time challenge and checks the signed answer against the stored public key."""

import base64
import hashlib
import hmac
import json
import secrets
import time

from django.conf import settings
from django.contrib.auth import login
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import throttle, webauthn
from .auth_views import _client_ip, _remember, _user_json, _with_fresh_csrf
from .models import Passkey
from .views import api_login_required, read_json_body

CHALLENGE_SECONDS = 5 * 60
MAX_PASSKEYS = 10
MAX_NAME = 60


def b64e(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def b64d(text):
    if not isinstance(text, str) or len(text) > 10_000:
        raise webauthn.WebAuthnError("bad base64")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except ValueError as exc:
        raise webauthn.WebAuthnError("bad base64") from exc


def _rp_id(request):
    if settings.WEBAUTHN_RP_ID:
        return settings.WEBAUTHN_RP_ID
    host = request.get_host()  # already checked against ALLOWED_HOSTS
    return host.rsplit(":", 1)[0] if not host.startswith("[") else host


def _origin(request):
    return settings.WEBAUTHN_ORIGIN or "%s://%s" % (request.scheme, request.get_host())


def _handle(user):
    # An opaque, stable id for the account (WebAuthn asks for one that is not the email).
    return hashlib.sha256(("%s:%s" % (settings.SECRET_KEY, user.pk)).encode()).digest()[:16]


def _new_challenge(request, purpose):
    raw = secrets.token_bytes(32)
    request.session["webauthn"] = {"c": b64e(raw), "p": purpose, "t": time.time()}
    return b64e(raw)


def _take_challenge(request, purpose):
    saved = request.session.pop("webauthn", None)
    if not saved or saved.get("p") != purpose or time.time() - saved.get("t", 0) > CHALLENGE_SECONDS:
        raise webauthn.WebAuthnError("the passkey request timed out, please try again")
    return saved["c"]


def _check_client_data(request, client_data_b64, kind, challenge):
    raw = b64d(client_data_b64)
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise webauthn.WebAuthnError("bad client data") from exc
    if (data.get("type") != kind or not isinstance(data.get("challenge"), str)
            or not hmac.compare_digest(data["challenge"], challenge)
            or data.get("origin") != _origin(request) or data.get("crossOrigin") is True):
        raise webauthn.WebAuthnError("this passkey answer does not belong to this site or request")
    return raw


def _check_flags(request, auth):
    if not hmac.compare_digest(auth["rp_id_hash"], hashlib.sha256(_rp_id(request).encode()).digest()):
        raise webauthn.WebAuthnError("this passkey is for a different site")
    if not (auth["flags"] & webauthn.FLAG_UP and auth["flags"] & webauthn.FLAG_UV):
        raise webauthn.WebAuthnError("the passkey must be unlocked with your fingerprint, face or screen lock")


def _bad(message, status=400):
    return JsonResponse({"error": message}, status=status)


# ---------------- add a passkey (signed-in user) ----------------

@require_POST
@api_login_required
def register_options(request):
    user = request.user
    if user.passkeys.count() >= MAX_PASSKEYS:
        return _bad("you already have %d passkeys, remove one first" % MAX_PASSKEYS)
    return JsonResponse({
        "challenge": _new_challenge(request, "register"),
        "rp": {"id": _rp_id(request), "name": "ResumeWise"},
        "user": {"id": b64e(_handle(user)), "name": user.email, "displayName": user.first_name or user.email},
        "pubKeyCredParams": [{"type": "public-key", "alg": -7}],
        "timeout": 60000, "attestation": "none",
        "authenticatorSelection": {"residentKey": "preferred", "userVerification": "required"},
        "excludeCredentials": [{"type": "public-key", "id": p.credential_id} for p in user.passkeys.all()],
    })


@require_POST
@api_login_required
def register_finish(request):
    data, error = read_json_body(request, ["id"])
    if error:
        return error
    resp = data.get("response")
    try:
        challenge = _take_challenge(request, "register")
        if not isinstance(resp, dict):
            raise webauthn.WebAuthnError("bad request")
        _check_client_data(request, resp.get("clientDataJSON"), "webauthn.create", challenge)
        attestation = webauthn.cbor_decode(b64d(resp.get("attestationObject")))
        if not isinstance(attestation, dict) or not isinstance(attestation.get("authData"), bytes):
            raise webauthn.WebAuthnError("bad attestation")
        auth = webauthn.parse_auth_data(attestation["authData"])  # attestation statement itself is not trusted or needed
        _check_flags(request, auth)
        if "credential_id" not in auth or b64e(auth["credential_id"]) != data["id"]:
            raise webauthn.WebAuthnError("credential id mismatch")
    except webauthn.WebAuthnError as exc:
        return _bad(str(exc))
    if request.user.passkeys.count() >= MAX_PASSKEYS:
        return _bad("you already have %d passkeys, remove one first" % MAX_PASSKEYS)
    if Passkey.objects.filter(credential_id=data["id"]).exists():
        return _bad("this passkey is already registered")
    x, y = auth["public_key"]
    name = " ".join(str(data.get("name") or "").split())[:MAX_NAME] or "Passkey %d" % (request.user.passkeys.count() + 1)
    row = Passkey.objects.create(user=request.user, credential_id=data["id"], key_x="%064x" % x, key_y="%064x" % y,
                                 sign_count=auth["counter"], name=name)
    return JsonResponse({"id": str(row.id), "name": row.name}, status=201)


# ---------------- sign in with a passkey ----------------

@require_POST
def login_options(request):
    return JsonResponse({"challenge": _new_challenge(request, "login"), "rpId": _rp_id(request),
                         "userVerification": "required", "timeout": 60000, "allowCredentials": []})


@require_POST
def login_finish(request):
    data, error = read_json_body(request, ["id"])
    if error:
        return error
    ip = _client_ip(request)
    if throttle.is_blocked("passkey-ip", ip, limit=throttle.ip_limit(10)):
        return _bad("too many attempts, try later", 429)
    resp = data.get("response")
    try:
        challenge = _take_challenge(request, "login")
        if not isinstance(resp, dict) or not isinstance(data["id"], str):
            raise webauthn.WebAuthnError("bad request")
        row = Passkey.objects.select_related("user").filter(credential_id=data["id"], user__is_active=True).first()
        if row is None:
            raise webauthn.WebAuthnError("this passkey is not registered here")
        client_raw = _check_client_data(request, resp.get("clientDataJSON"), "webauthn.get", challenge)
        auth_raw = b64d(resp.get("authenticatorData"))
        auth = webauthn.parse_auth_data(auth_raw)
        _check_flags(request, auth)
        handle = resp.get("userHandle")
        if handle and not hmac.compare_digest(b64d(handle), _handle(row.user)):
            raise webauthn.WebAuthnError("this passkey belongs to another account")
        point = (int(row.key_x, 16), int(row.key_y, 16))
        signed = auth_raw + hashlib.sha256(client_raw).digest()
        if not webauthn.ecdsa_verify(point, signed, b64d(resp.get("signature"))):
            raise webauthn.WebAuthnError("the passkey signature is not valid")
        if (auth["counter"] or row.sign_count) and auth["counter"] <= row.sign_count:
            raise webauthn.WebAuthnError("this passkey looks cloned, it was refused")
    except webauthn.WebAuthnError as exc:
        throttle.record_failure("passkey-ip", ip)
        return _bad(str(exc), 401)
    row.sign_count, row.last_used_at = auth["counter"], timezone.now()
    row.save(update_fields=["sign_count", "last_used_at"])
    login(request, row.user)  # a passkey is already two factors (the device plus fingerprint/face/PIN)
    _remember(request, True)
    return JsonResponse(_with_fresh_csrf(request, _user_json(row.user)))


# ---------------- manage ----------------

@require_GET
@api_login_required
def passkey_list(request):
    return JsonResponse({"passkeys": [
        {"id": str(p.id), "name": p.name, "created_at": p.created_at.isoformat(),
         "last_used_at": p.last_used_at.isoformat() if p.last_used_at else None}
        for p in request.user.passkeys.order_by("created_at")]})


@require_http_methods(["DELETE"])
@api_login_required
def passkey_delete(request, passkey_id):
    deleted, _ = Passkey.objects.filter(id=passkey_id, user=request.user).delete()
    if not deleted:
        return _bad("not found", 404)
    return JsonResponse({"status": "passkey removed"})
