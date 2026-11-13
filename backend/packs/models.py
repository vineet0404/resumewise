"""Database models.

Written to run unchanged on PostgreSQL, Oracle and SQL Server:
- UUID primary keys created by Django, no database-specific id syntax.
- JSON is stored as validated text in a TextField, not a native JSON type.
- Money is whole paise (integers), time is stored in UTC.
- No raw SQL, no arrays, no partial indexes, no database-specific features.
- Short lower-case names.
"""

import json
import uuid

from django.conf import settings
from django.db import models


class JsonTextMixin:
    """Helpers to keep a JSON document in a TextField."""

    @staticmethod
    def dump(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def load(text):
        return json.loads(text) if text else None


class Profile(models.Model, JsonTextMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profiles")
    parsed_json = models.TextField()
    source_file_key = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True)  # auto-delete date; a nightly job removes expired rows
    template_key = models.CharField(max_length=30, default="classic")
    # Share link (step 13): a secret address that shows a read-only copy of this CV. None = sharing is off.
    share_token = models.CharField(max_length=64, null=True, unique=True)
    share_template = models.CharField(max_length=30, blank=True)  # empty = use the CV's own template
    share_contact = models.BooleanField(default=False)  # show email and phone on the shared page
    share_photo = models.BooleanField(default=False)  # show the photo on the shared page
    share_views = models.PositiveIntegerField(default=0)  # how many times the link was opened (no addresses kept)

    @property
    def parsed(self):
        return self.load(self.parsed_json)


class Job(models.Model, JsonTextMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jobs")
    title = models.CharField(max_length=200)
    company = models.CharField(max_length=200, blank=True)
    raw_text = models.TextField()
    requirements_json = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True)
    # Job tracker (step 5): where the person is with this job
    url = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, default="saved")  # saved, applied, interview, offer, rejected
    notes = models.TextField(blank=True)
    score = models.PositiveSmallIntegerField(null=True)  # last match score against the person's CV
    answers_json = models.TextField(blank=True)  # interview practice answers {question id: text}
    updated_at = models.DateTimeField(auto_now=True)
    applied_on = models.DateField(null=True)  # set when the person marks the job as applied
    follow_up_on = models.DateField(null=True)  # the day to follow up (default: 7 days after applying)
    reminded_at = models.DateTimeField(null=True)  # when the reminder email was sent (None = not yet)
    remind_email = models.BooleanField(default=True)  # the person may switch the reminder email off per job


class Run(models.Model):
    STATUSES = ("queued", "running", "needs_review", "ready", "failed")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="runs")
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=20, default="queued")
    match_score = models.PositiveSmallIntegerField(null=True)
    ats_score = models.PositiveSmallIntegerField(null=True)
    cost_paise = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)


class Output(models.Model, JsonTextMixin):
    KINDS = ("resume", "cover_letter", "email", "interview")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="outputs")
    kind = models.CharField(max_length=20)
    content_json = models.TextField()
    file_key = models.CharField(max_length=255, blank=True)
    verified_at = models.DateTimeField(null=True)


class Claim(models.Model):
    ACKS = ("pending", "confirmed", "removed")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    output = models.ForeignKey(Output, on_delete=models.CASCADE, related_name="claims")
    line_ref = models.CharField(max_length=64)
    label = models.CharField(max_length=16)  # supported, reworded, new
    source_id = models.CharField(max_length=64, blank=True)
    user_ack = models.CharField(max_length=16, default="pending")
    reason = models.CharField(max_length=200, blank=True)


class ProfileVersion(models.Model):
    """A saved copy of a profile from before a change, so the user can undo."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="versions")
    parsed_json = models.TextField()
    reason = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ProfilePhoto(models.Model):
    """The user's formal photo, cleaned by core.image_check. Deleted with the profile."""

    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="photo")
    content_type = models.CharField(max_length=20)
    data = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)


class Account(models.Model):
    """Extra sign-in facts about a user. A user with no row here is an older account:
    treated as email-verified, no two-factor."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account")
    email_verified_at = models.DateTimeField(null=True)
    totp_secret = models.CharField(max_length=200, blank=True)  # encrypted, see security.py
    totp_enabled = models.BooleanField(default=False)
    totp_last_step = models.BigIntegerField(default=0)  # a code can be used only once
    recovery_json = models.TextField(blank=True)  # SHA-256 hashes of unused recovery codes
    pro_until = models.DateTimeField(null=True)  # paid plan runs until this moment (None or past = free plan)


class EmailToken(models.Model):
    """One-time link tokens (email verify, magic login). Only a hash is stored."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_tokens")
    purpose = models.CharField(max_length=20)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Passkey(models.Model):
    """A WebAuthn public key. The private key never leaves the person's device."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="passkeys")
    credential_id = models.CharField(max_length=512, unique=True)  # base64url
    key_x = models.CharField(max_length=64)  # P-256 public key, hex
    key_y = models.CharField(max_length=64)
    sign_count = models.BigIntegerField(default=0)
    name = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True)


class ErrorEvent(models.Model):
    """One server error (HTTP 500), kept 30 days so the owner can see problems. No request body, no query string."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=200)
    kind = models.CharField(max_length=100)       # exception class name
    message = models.CharField(max_length=300, blank=True)
    user_id = models.PositiveBigIntegerField(null=True)


class Feedback(models.Model):
    """A note the person sent with the feedback button. Deleted with the account."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="feedback")
    kind = models.CharField(max_length=20, default="other")  # idea, problem, other
    message = models.TextField()
    page = models.CharField(max_length=40, blank=True)  # which tab they were on
    created_at = models.DateTimeField(auto_now_add=True)


class Payment(models.Model):
    """One purchase (a Razorpay Payment Link). Kept for accounting even if the person deletes their account
    (the user link is then emptied; no name or email is stored here)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="payments")
    reference = models.CharField(max_length=40, unique=True)  # our own id, sent to Razorpay as reference_id
    plan_key = models.CharField(max_length=30)
    days = models.PositiveIntegerField()
    amount_paise = models.PositiveIntegerField()
    status = models.CharField(max_length=12, default="created")  # created, paid, refunded
    link_id = models.CharField(max_length=60, blank=True)
    link_url = models.CharField(max_length=300, blank=True)
    payment_id = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True)
