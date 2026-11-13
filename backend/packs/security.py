"""Small helpers shared by the sign-in features."""

import base64
import hashlib
import hmac
import json
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import Account, EmailToken


# ---- one-time email tokens (verify email, magic login) ----

def _hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_token(user, purpose, ttl_seconds):
    """Returns the raw token (goes in the email). Only its hash is stored."""
    raw = secrets.token_urlsafe(32)
    EmailToken.objects.filter(user=user, purpose=purpose, used_at=None).delete()  # newest link wins
    EmailToken.objects.create(user=user, purpose=purpose, token_hash=_hash(raw),
                              expires_at=timezone.now() + timedelta(seconds=ttl_seconds))
    return raw


def consume_token(raw, purpose):
    """Returns the user once, or None if the token is unknown, used, expired or for another purpose."""
    if not isinstance(raw, str) or not 20 <= len(raw) <= 100:
        return None
    with transaction.atomic():
        row = EmailToken.objects.select_for_update().filter(token_hash=_hash(raw), purpose=purpose).select_related("user").first()
        if row is None or row.used_at is not None or row.expires_at < timezone.now() or not row.user.is_active:
            return None
        row.used_at = timezone.now()
        row.save(update_fields=["used_at"])
        return row.user


# ---- account facts ----

def account_of(user):
    return Account.objects.filter(user=user).first()


def is_verified(user):
    acc = account_of(user)
    return acc is None or acc.email_verified_at is not None  # no row = older account


def mark_verified(user):
    acc, _ = Account.objects.get_or_create(user=user, defaults={"email_verified_at": timezone.now()})
    if acc.email_verified_at is None:
        acc.email_verified_at = timezone.now()
        acc.save(update_fields=["email_verified_at"])


def ensure_account(user):
    acc, _ = Account.objects.get_or_create(user=user, defaults={"email_verified_at": timezone.now()})
    return acc


# ---- protecting the 2FA secret inside the database ----
# A database leak alone should not hand out the secrets: they are XOR-ed with a keystream
# made from SECRET_KEY (HMAC-SHA256 in counter mode) and a random nonce per value.

def _stream(nonce, length):
    key = hashlib.sha256(("totp-secret:" + settings.SECRET_KEY).encode()).digest()
    out = b""
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    return out[:length]


def seal(text):
    nonce = secrets.token_bytes(16)
    data = text.encode()
    body = bytes(a ^ b for a, b in zip(data, _stream(nonce, len(data))))
    tag = hmac.new(_stream(nonce + b"mac", 32), nonce + body, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(nonce + body + tag).decode()


def unseal(blob):
    try:
        raw = base64.urlsafe_b64decode(blob.encode())
        nonce, body, tag = raw[:16], raw[16:-16], raw[-16:]
        want = hmac.new(_stream(nonce + b"mac", 32), nonce + body, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(tag, want):
            return None
        return bytes(a ^ b for a, b in zip(body, _stream(nonce, len(body)))).decode()
    except (ValueError, UnicodeDecodeError):
        return None


# ---- recovery codes ----

def new_recovery_codes(count=8):
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return ["".join(secrets.choice(alphabet) for _ in range(5)) + "-" + "".join(secrets.choice(alphabet) for _ in range(5))
            for _ in range(count)]


def hash_recovery(code):
    return hashlib.sha256("".join(code.lower().split()).replace("-", "").encode()).hexdigest()


def load_recovery(acc):
    try:
        return json.loads(acc.recovery_json or "[]")
    except ValueError:
        return []


# ---- the emails ----

VERIFY_TTL = 3 * 24 * 3600
MAGIC_TTL = 15 * 60


def send_verify_email(request, user):
    raw = issue_token(user, "verify", VERIFY_TTL)
    link = request.build_absolute_uri("/") + "#verify=" + raw  # after "#": stays out of server logs
    send_mail("Confirm your email for ResumeWise",
              "Hi %s,\n\nPlease confirm this is your email address:\n\n%s\n\nThe link works once, for 3 days.\n"
              "If you did not create an account, ignore this email.\n" % (user.first_name or "there", link),
              None, [user.email], fail_silently=True)


def send_magic_email(request, user):
    raw = issue_token(user, "magic", MAGIC_TTL)
    link = request.build_absolute_uri("/") + "#magic=" + raw
    send_mail("Your ResumeWise login link",
              "Hi %s,\n\nClick to log in (works once, for 15 minutes):\n\n%s\n\n"
              "If you did not ask for this, ignore this email. Nobody can log in without it.\n" % (user.first_name or "there", link),
              None, [user.email], fail_silently=True)
