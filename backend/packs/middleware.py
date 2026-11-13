"""Remember server errors in the database so the admin dashboard can show them (never crashes the request)."""

import re

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class ErrorCaptureMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        try:
            from .models import ErrorEvent
            user = getattr(request, "user", None)
            from . import alerts
            alerts.notify(type(exception).__name__[:100], _UUID.sub("<id>", request.path)[:200], str(exception)[:300])
            ErrorEvent.objects.create(
                method=request.method[:10], path=_UUID.sub("<id>", request.path)[:200],
                kind=type(exception).__name__[:100], message=str(exception)[:300],
                user_id=user.pk if user is not None and user.is_authenticated else None)
        except Exception:  # noqa: BLE001  never let logging break the answer
            pass
        return None
