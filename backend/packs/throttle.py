"""Small failure counter to slow down password guessing.

Uses Django's cache. The default cache is per process, so before running more
than one server process, configure a shared cache (for example the database
cache: CACHES backend DatabaseCache plus `manage.py createcachetable`).
"""

from django.conf import settings
from django.core.cache import cache

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60


def _key(scope, ident):
    return "throttle:%s:%s" % (scope, ident)


def is_blocked(scope, ident, limit=MAX_FAILURES, window=WINDOW_SECONDS):  # noqa: ARG001  (window is only used when counting)
    return cache.get(_key(scope, ident), 0) >= limit


def record_failure(scope, ident, window=WINDOW_SECONDS):
    key = _key(scope, ident)
    cache.add(key, 0, window)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)


count = record_failure  # same thing, a better name when it counts successes (for example new accounts)


def clear(scope, ident):
    cache.delete(_key(scope, ident))


def ip_limit(per_person):
    """Limit for an *IP address*. Many people can share one address (college Wi-Fi, office, phone network),
    so per-IP limits are the per-person limit times IP_LIMIT_MULTIPLIER. Per-account limits are not multiplied."""
    return per_person * max(1, int(getattr(settings, "IP_LIMIT_MULTIPLIER", 1)))
