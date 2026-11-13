"""Authenticator-app codes (RFC 6238 / RFC 4226), standard library only.

Works with Google Authenticator, Microsoft Authenticator, Authy, 1Password and similar:
SHA-1, 6 digits, 30 second steps.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

STEP_SECONDS = 30
DIGITS = 6


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret_b32):
    return base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)


def hotp(key, counter, digits=DIGITS):
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    number = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(number).zfill(digits)


def code_at(secret_b32, when=None):
    step = int((time.time() if when is None else when) // STEP_SECONDS)
    return hotp(_key(secret_b32), step)


def check(secret_b32, code, last_step=0, when=None, window=1):
    """Returns the matching time step, or None. A step at or before last_step is refused (no reuse)."""
    code = "".join(str(code).split())
    if len(code) != DIGITS or not code.isdigit():
        return None
    now = int((time.time() if when is None else when) // STEP_SECONDS)
    key = _key(secret_b32)
    hit = None
    for step in range(now - window, now + window + 1):  # no early exit: same work for every guess
        if hmac.compare_digest(hotp(key, step), code) and step > last_step:
            hit = step
    return hit


def otpauth_uri(secret_b32, email, issuer="ResumeWise"):
    label = urllib.parse.quote("%s:%s" % (issuer, email))
    query = urllib.parse.urlencode({"secret": secret_b32, "issuer": issuer, "algorithm": "SHA1",
                                    "digits": DIGITS, "period": STEP_SECONDS})
    return "otpauth://totp/%s?%s" % (label, query)
