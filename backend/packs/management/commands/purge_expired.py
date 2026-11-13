"""Delete profiles and jobs past their expiry date.

Run nightly (cron or a scheduler). Related runs, outputs and claims are removed
with them. Files in object storage must be deleted by the same job once file
storage is added.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from datetime import timedelta

from packs.models import EmailToken, ErrorEvent, Job, Profile


class Command(BaseCommand):
    help = "Delete expired profiles and jobs (the 30-day retention promise)."

    def handle(self, *args, **options):
        now = timezone.now()
        profiles, _ = Profile.objects.filter(expires_at__lt=now).delete()
        jobs, _ = Job.objects.filter(expires_at__lt=now).delete()
        EmailToken.objects.filter(expires_at__lt=now).delete()  # used or expired sign-in links
        ErrorEvent.objects.filter(created_at__lt=now - timedelta(days=30)).delete()
        self.stdout.write("Deleted %d profile rows and %d job rows (including related records)." % (profiles, jobs))
