"""Tell the owner by email when the server breaks (set ALERT_EMAIL). Throttled so one bug sends one email, not thousands."""

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail

WINDOW_SECONDS = 600  # at most one email per kind of error per 10 minutes


def notify(kind, path, message):
    """Best effort: never raises, never slows the request more than one email send."""
    to = getattr(settings, "ALERT_EMAIL", "")
    if not to:
        return False
    try:
        key = "alert:%s:%s" % (kind, path)
        if not cache.add(key, 1, WINDOW_SECONDS):
            return False
        send_mail("[ResumeWise] server error: %s" % kind,
                  "A request to %s failed.\nType: %s\nMessage: %s\n\nThe Admin tab shows the latest errors. "
                  "More of the same error in the next %d minutes will not be emailed.\n" % (path, kind, message, WINDOW_SECONDS // 60),
                  None, [a.strip() for a in to.split(",") if a.strip()], fail_silently=True)
        return True
    except Exception:  # noqa: BLE001
        return False
