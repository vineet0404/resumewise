"""Our own "are you a bot?" check. No Google, no CAPTCHA pictures, no tracking.

Three cheap checks together:
1. A signed token with the time it was made. A form filled in under 2 seconds or sent after an hour fails.
2. A hidden "website" field that people never see. Bots fill every field.
3. A small proof of work: the browser must find a number so that sha256(token + ":" + number) starts with
   POW_BITS zero bits (about 16 000 tries, under a second, done while the person types). It costs a real person
   nothing, but a bot that signs up thousands of accounts pays for every one.
A token works once (the cache remembers it), so one solved challenge cannot be reused.
"""

import hashlib
import secrets
import time

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET

MIN_AGE = 2
MAX_AGE = 3600
POW_BITS = 14
_SALT = "resumewise.botcheck"


def enabled():
    return bool(getattr(settings, "BOT_CHECK", True))


def new_challenge():
    token = signing.dumps({"t": int(time.time()), "n": secrets.token_hex(8)}, salt=_SALT)
    return {"token": token, "bits": POW_BITS, "min_wait": MIN_AGE}


def _leading_zero_bits(digest):
    bits = 0
    for byte in digest:
        if byte == 0:
            bits += 8
            continue
        bits += 8 - byte.bit_length()
        break
    return bits


def solve(token, bits=POW_BITS):
    """Reference solver (the browser has its own copy in app.js). Used by the tests."""
    n = 0
    while True:
        if _leading_zero_bits(hashlib.sha256(("%s:%d" % (token, n)).encode()).digest()) >= bits:
            return n
        n += 1


def check(data):
    """None if the person passed, otherwise a short reason (shown as a generic message)."""
    if not enabled():
        return None
    if str(data.get("website") or "").strip():
        return "hidden field filled"
    token = data.get("bot_token")
    nonce = data.get("bot_nonce")
    if not isinstance(token, str) or not token or len(token) > 400:
        return "missing token"
    try:
        info = signing.loads(token, salt=_SALT, max_age=MAX_AGE)
    except signing.BadSignature:
        return "bad or old token"
    if time.time() - info["t"] < MIN_AGE:
        return "too fast"
    try:
        nonce_int = int(nonce)
    except (TypeError, ValueError):
        return "missing work"
    if nonce_int < 0 or nonce_int > 10 ** 12:
        return "missing work"
    if _leading_zero_bits(hashlib.sha256(("%s:%d" % (token, nonce_int)).encode()).digest()) < POW_BITS:
        return "work not done"
    if not cache.add("botcheck:used:" + hashlib.sha256(token.encode()).hexdigest(), 1, MAX_AGE):
        return "token used before"
    return None


def reject():
    return JsonResponse({"error": "could not confirm you are a person; reload the page and try again", "code": "bot_check"}, status=400)


@require_GET
def challenge(request):
    response = JsonResponse(new_challenge())
    response["Cache-Control"] = "no-store"
    return response
