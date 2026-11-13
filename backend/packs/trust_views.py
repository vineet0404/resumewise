"""Feedback button. A short note from a signed-in person; the owner reads it in the Admin tab."""

from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Feedback
from .views import api_login_required, read_json_body

KINDS = ("idea", "problem", "other")
MAX_MESSAGE = 2000
PER_DAY = 10


@require_POST
@api_login_required
def feedback(request):
    data, error = read_json_body(request, [])
    if error:
        return error
    message = data.get("message")
    if not isinstance(message, str) or len(message.strip()) < 5:
        return JsonResponse({"error": "please write a few words"}, status=400)
    message = message.strip()
    if len(message) > MAX_MESSAGE:
        return JsonResponse({"error": "message is too long (limit %d characters)" % MAX_MESSAGE}, status=413)
    kind = data.get("kind", "other")
    if kind not in KINDS:
        return JsonResponse({"error": "kind must be one of: " + ", ".join(KINDS)}, status=400)
    page = data.get("page", "")
    page = page[:40] if isinstance(page, str) else ""
    since = timezone.now() - timedelta(hours=24)
    if Feedback.objects.filter(user=request.user, created_at__gte=since).count() >= PER_DAY:
        return JsonResponse({"error": "too many messages today, please try again tomorrow"}, status=429)
    Feedback.objects.create(user=request.user, kind=kind, message=message, page=page)
    return JsonResponse({"status": "thank you"}, status=201)
