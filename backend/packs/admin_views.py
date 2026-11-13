"""Owner dashboard: numbers only, for staff accounts. Never shows a person's CV, job text or notes."""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import Account, ErrorEvent, Feedback, Job, Payment, Profile, Run
from .views import api_login_required


@require_GET
@api_login_required
def stats(request):
    if not request.user.is_staff:
        return JsonResponse({"error": "not found"}, status=404)
    now = timezone.now()
    day, week = now - timedelta(hours=24), now - timedelta(days=7)
    users = get_user_model().objects
    runs_24h = Run.objects.filter(started_at__gte=day)
    errors = ErrorEvent.objects.filter(created_at__gte=day)
    recent = ErrorEvent.objects.order_by("-created_at")[:20]
    return JsonResponse({
        "users": {"total": users.count(), "new_24h": users.filter(date_joined__gte=day).count(),
                  "new_7d": users.filter(date_joined__gte=week).count(),
                  "email_verified": Account.objects.exclude(email_verified_at=None).count()},
        "cvs": {"active": Profile.objects.filter(expires_at__gt=now).count(), "new_24h": Profile.objects.filter(created_at__gte=day).count()},
        "jobs": {"saved": Job.objects.count()},
        "ai": {"runs_24h": runs_24h.count(), "spent_24h_paise": runs_24h.aggregate(t=Sum("cost_paise"))["t"] or 0,
               "budget_paise": settings.AI_DAILY_BUDGET_PAISE, "per_user_limit": settings.AI_DAILY_PER_USER},
        "feedback": [{"time": f.created_at.isoformat(), "kind": f.kind, "page": f.page, "email": f.user.email, "message": f.message}
                     for f in Feedback.objects.select_related("user").order_by("-created_at")[:20]],
        "money": {"paid_30d": Payment.objects.filter(status="paid", paid_at__gte=now - timedelta(days=30)).count(),
                  "revenue_30d_paise": Payment.objects.filter(status="paid", paid_at__gte=now - timedelta(days=30)).aggregate(t=Sum("amount_paise"))["t"] or 0,
                  "pro_now": Account.objects.filter(pro_until__gt=now).count()},
        "errors": {"count_24h": errors.count(),
                   "recent": [{"time": e.created_at.isoformat(), "method": e.method, "path": e.path, "kind": e.kind, "message": e.message}
                              for e in recent]},
    })
