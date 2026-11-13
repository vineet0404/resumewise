"""Sign in with Google or LinkedIn, written by hand (standard library only, no OAuth package).

Both use OpenID Connect "authorization code" flow: /start sends the browser to the provider;
the provider sends it back to /callback with a one-time code; this server swaps the code for
an ID token by talking to the provider directly over HTTPS (that direct, TLS-protected reply
is why the token needs no signature check), checks it is for this app and this login attempt,
then signs the user in.

A provider is switched on only when its client ID and secret are both set.
"""

import base64
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.views.decorators.http import require_GET

from . import throttle
from . import security
from .auth_views import MAX_NAME, _client_ip, finish_login

NAMES = ("google", "linkedin")
ISSUERS = {"google": ("https://accounts.google.com", "accounts.google.com"),
           "linkedin": ("https://www.linkedin.com/oauth",)}
SCOPE = "openid email profile"  # LinkedIn and Google both accept these three


def _cfg(name):
    """Settings for one provider, read at call time. None if the provider is not switched on."""
    if name not in NAMES:
        return None
    up = name.upper()
    cfg = {"id": getattr(settings, up + "_CLIENT_ID", ""), "secret": getattr(settings, up + "_CLIENT_SECRET", ""),
           "auth_url": getattr(settings, up + "_AUTH_URL"), "token_url": getattr(settings, up + "_TOKEN_URL"),
           "redirect": getattr(settings, up + "_REDIRECT_URI", ""), "issuers": ISSUERS[name]}
    return cfg if cfg["id"] and cfg["secret"] else None


def configured(name):
    return _cfg(name) is not None


def _redirect_uri(request, name, cfg):
    return cfg["redirect"] or request.build_absolute_uri("/v1/auth/%s/callback" % name)


def _fail(reason="failed"):
    return HttpResponseRedirect("/#signin=" + reason)


@require_GET
def providers(request):
    return JsonResponse({"google": configured("google"), "linkedin": configured("linkedin"), "passkeys": True})


@require_GET
def start(request, provider):
    cfg = _cfg(provider)
    if cfg is None:
        raise Http404()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    request.session["oauth_" + provider] = {"state": state, "nonce": nonce}
    params = {"client_id": cfg["id"], "redirect_uri": _redirect_uri(request, provider, cfg),
              "response_type": "code", "scope": SCOPE, "state": state, "nonce": nonce}
    if provider == "google":
        params["prompt"] = "select_account"
    return HttpResponseRedirect(cfg["auth_url"] + "?" + urllib.parse.urlencode(params))


def _exchange(request, provider, cfg, code):
    """Trade the one-time code for the ID token's claims. Returns a dict or None."""
    body = urllib.parse.urlencode({
        "code": code, "client_id": cfg["id"], "client_secret": cfg["secret"],
        "redirect_uri": _redirect_uri(request, provider, cfg), "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(cfg["token_url"], data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            reply = json.loads(resp.read(1_000_000))
        payload = reply["id_token"].split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def _claims_ok(claims, cfg, nonce):
    if not isinstance(claims, dict) or not nonce:
        return False
    verified = claims.get("email_verified") in (True, "true")
    try:
        fresh = float(claims.get("exp", 0)) > time.time()
    except (TypeError, ValueError):
        fresh = False
    return (claims.get("aud") == cfg["id"] and claims.get("iss") in cfg["issuers"] and fresh
            and verified and isinstance(claims.get("email"), str) and "@" in claims["email"]
            and isinstance(claims.get("nonce"), str) and hmac.compare_digest(claims["nonce"], nonce))


@require_GET
def callback(request, provider):
    cfg = _cfg(provider)
    if cfg is None:
        raise Http404()
    ip = _client_ip(request)
    if throttle.is_blocked("oauth-ip", ip, limit=throttle.ip_limit(10)):
        return _fail("failed")
    saved = request.session.pop("oauth_" + provider, None) or {}
    state, nonce = saved.get("state", ""), saved.get("nonce", "")
    if request.GET.get("error") in ("access_denied", "user_cancelled_login", "user_cancelled_authorize"):
        return _fail("denied")
    got_state = request.GET.get("state", "")
    code = request.GET.get("code", "")
    if not state or not code or not hmac.compare_digest(got_state, state):
        throttle.record_failure("oauth-ip", ip)
        return _fail()
    claims = _exchange(request, provider, cfg, code)
    if not _claims_ok(claims, cfg, nonce):
        throttle.record_failure("oauth-ip", ip)
        return _fail()
    email = claims["email"].strip().lower()
    User = get_user_model()
    user = User.objects.filter(username=email).first()  # same verified email: same account
    if user is None:
        name = " ".join(str(claims.get("name") or "").split())[:MAX_NAME]
        user = User(username=email, email=email, first_name=name)
        user.set_unusable_password()  # provider-only account; "forgot password" can add one later
        user.save()
    elif not user.is_active:
        return _fail()
    if not finish_login(request, user, True, verified_email=True):  # the provider already verified the email
        return HttpResponseRedirect("/#signin=2fa")
    return HttpResponseRedirect("/")
