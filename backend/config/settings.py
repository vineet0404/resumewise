"""Django settings. Everything environment-specific comes from environment variables."""

import os
from pathlib import Path

from .dburl import parse_database_url

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes")


DEBUG = env_bool("DEBUG", False)

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key"
    else:
        raise RuntimeError("Set the SECRET_KEY environment variable (or DEBUG=1 for local work).")

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "packs",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "packs.middleware.ErrorCaptureMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": parse_database_url(os.environ.get("DATABASE_URL", "sqlite:///db.sqlite3"))}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

USE_TZ = True
TIME_ZONE = os.environ.get("TIME_ZONE", "Asia/Kolkata")  # days (follow-up reminders) follow this zone; times are stored in UTC

# Security headers and cookies. Strict by default, relaxed only in local DEBUG mode.
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Sign-in sessions. "Remember me" keeps the session 30 days; otherwise it ends when the browser closes.
SESSION_REMEMBER_SECONDS = 30 * 24 * 3600
PASSWORD_RESET_TIMEOUT = 60 * 60  # a reset link works for 1 hour, once

# Email (password reset). Local default prints the email in the server window.
# For real sending set EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend plus EMAIL_HOST,
# EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_USE_TLS (any SMTP service works).
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "ResumeWise <no-reply@resumewise.local>")

# Sign in with Google (optional). Create an "OAuth client ID" (type: Web application) in Google Cloud
# Console and add this exact redirect URI there: http://127.0.0.1:8000/v1/auth/google/callback
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")  # leave empty to derive it from the request
GOOGLE_AUTH_URL = os.environ.get("GOOGLE_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth")  # only changed in tests
GOOGLE_TOKEN_URL = os.environ.get("GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token")

# Sign in with LinkedIn (optional). In the LinkedIn Developer Portal create an app, add the product
# "Sign In with LinkedIn using OpenID Connect", and add this redirect URL:
# http://127.0.0.1:8000/v1/auth/linkedin/callback
LINKEDIN_CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
LINKEDIN_REDIRECT_URI = os.environ.get("LINKEDIN_REDIRECT_URI", "")
LINKEDIN_AUTH_URL = os.environ.get("LINKEDIN_AUTH_URL", "https://www.linkedin.com/oauth/v2/authorization")
LINKEDIN_TOKEN_URL = os.environ.get("LINKEDIN_TOKEN_URL", "https://www.linkedin.com/oauth/v2/accessToken")

# Passkeys (WebAuthn). Locally the site must be opened as http://localhost:8000 (a bare IP address
# is not allowed as a passkey site name). In production leave these empty, or set them to your
# domain, e.g. WEBAUTHN_RP_ID=example.com and WEBAUTHN_ORIGIN=https://example.com
WEBAUTHN_RP_ID = os.environ.get("WEBAUTHN_RP_ID", "")
WEBAUTHN_ORIGIN = os.environ.get("WEBAUTHN_ORIGIN", "")

# Many users at once. See README "Many users at once".
# IP address limits (sign-up, login failures, e-mail links...) are multiplied by this, because one address can be a
# whole college or office. Limits per account (5 wrong passwords per e-mail) stay strict.
IP_LIMIT_MULTIPLIER = int(os.environ.get("IP_LIMIT_MULTIPLIER", "5"))
# Number of reverse proxies / load balancers in front of Django (0 = none). Needed so each visitor is counted by
# their own address and not by the load balancer's.
TRUSTED_PROXIES = int(os.environ.get("TRUSTED_PROXIES", "0"))
# Shared counters for several server processes: CACHE_BACKEND=db, then run `python manage.py createcachetable` once.
if os.environ.get("CACHE_BACKEND", "").lower() == "db":
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "django_cache"}}
# Most AI calls running at the same time in one server process; extra callers get "busy, try again" instead of
# piling up and making every other page slow.
AI_MAX_CONCURRENT = int(os.environ.get("AI_MAX_CONCURRENT", "4"))

# Input limits
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
MAX_TEXT_CHARS = 200_000


# --- abuse protection (step 8) ---
import sys as _sys  # noqa: E402
BOT_CHECK = env_bool("BOT_CHECK", "test" not in _sys.argv)  # the tests turn it on only where they test it
AI_DAILY_PER_USER = int(os.environ.get("AI_DAILY_PER_USER", "15"))               # tailoring runs per person per 24 h
AI_DAILY_BUDGET_PAISE = int(os.environ.get("AI_DAILY_BUDGET_PAISE", "50000"))    # all people together: 500 rupees per 24 h
SIGNUPS_PER_IP_PER_DAY = int(os.environ.get("SIGNUPS_PER_IP_PER_DAY", "10"))     # multiplied by IP_LIMIT_MULTIPLIER


# --- deploy (step 12) ---
# Email the owner when the server breaks (comma separated; empty = off). Needs real email settings above.
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "")
# Needed only when the site is opened under another https name than ALLOWED_HOSTS shows (e.g. https://www.example.com).
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
# Where `manage.py backup` writes files, and how many days it keeps.
BACKUP_DIR = os.environ.get("BACKUP_DIR", str(BASE_DIR / "backups"))
BACKUP_KEEP_DAYS = int(os.environ.get("BACKUP_KEEP_DAYS", "14"))
# Logs go to the console (the process manager or Docker collects them). Never log request bodies.
LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}


# --- payments (step 15): Razorpay Payment Links. Keys come from the Razorpay dashboard (use TEST keys first). ---
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")  # the secret you type when you add the webhook
RAZORPAY_API = os.environ.get("RAZORPAY_API", "https://api.razorpay.com")  # only changed in tests
# The public address of the site, used for the page Razorpay sends people back to (e.g. https://resumewise.example.com).
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")
# Paid plans: passes for a number of days, no automatic renewal. Prices are in paise (14900 = Rs 149). You decide them.
PLANS = {
    "pro_30": {"label": "Pro, 30 days", "days": 30, "price_paise": int(os.environ.get("PRO_30_PRICE_PAISE", "14900"))},
    "pro_90": {"label": "Pro, 90 days", "days": 90, "price_paise": int(os.environ.get("PRO_90_PRICE_PAISE", "34900"))},
}
# Limits per person. "Pro" uses AI_DAILY_PER_USER and MAX_JOBS (100). While payments are not set up (no keys) nobody is
# held to the free limits: everyone gets the Pro limits.
FREE_AI_PER_DAY = int(os.environ.get("FREE_AI_PER_DAY", "3"))
FREE_MAX_JOBS = int(os.environ.get("FREE_MAX_JOBS", "10"))
