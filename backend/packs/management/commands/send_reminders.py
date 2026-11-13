"""Email people about jobs they applied for and should follow up on.

Run once a day (cron or a scheduler). One email per person, listing job title and company only
(never notes, CV lines or job text). Only people with a confirmed email get it, only for jobs
still at "applied" whose follow-up day has come, and each reminder is sent once (changing the
follow-up day arms it again). `--dry-run` shows what would be sent.
"""

from collections import defaultdict

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from packs import security
from packs.models import Job


def build_message(name, jobs, today):
    lines = ["Hi %s," % (name or "there"), "", "These jobs are waiting for a follow-up:", ""]
    for job in jobs:
        days = (today - job.applied_on).days if job.applied_on else None
        label = job.title + (" - " + job.company if job.company else "")
        lines.append("  * %s%s" % (label, " (applied %d days ago)" % days if days is not None else ""))
    lines += ["", "A short, polite message to the recruiter a week after applying is normal.",
              "Open ResumeWise > Jobs to snooze a reminder, switch it off, or change the status.", "",
              "You get this email because you applied for these jobs and kept reminders on."]
    return "\n".join(lines) + "\n"


class Command(BaseCommand):
    help = "Send follow-up reminder emails (run daily)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="show what would be sent, send nothing")

    def handle(self, *args, **options):
        today = timezone.localdate()
        due = (Job.objects.filter(status="applied", remind_email=True, reminded_at__isnull=True, follow_up_on__lte=today)
               .select_related("user").order_by("follow_up_on"))
        per_user = defaultdict(list)
        for job in due:
            per_user[job.user].append(job)
        sent = skipped = 0
        for user, jobs in per_user.items():
            if not user.email or not user.is_active or not security.is_verified(user):
                skipped += 1
                continue
            if options["dry_run"]:
                self.stdout.write("would email %s about %d job(s)" % (user.email, len(jobs)))
                continue
            send_mail("Time to follow up on %d job application%s" % (len(jobs), "" if len(jobs) == 1 else "s"),
                      build_message(user.first_name, jobs, today), None, [user.email], fail_silently=False)
            Job.objects.filter(id__in=[j.id for j in jobs]).update(reminded_at=timezone.now())
            sent += 1
        self.stdout.write("Reminder emails sent: %d. Skipped (unconfirmed or inactive): %d." % (sent, skipped))
