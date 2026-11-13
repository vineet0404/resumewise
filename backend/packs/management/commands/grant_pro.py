"""Give someone the Pro plan by hand (a friend, a college deal, a refund by other means).

    python manage.py grant_pro person@example.com 30     # add 30 days
    python manage.py grant_pro person@example.com 0      # switch Pro off now
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from packs.billing import _account


class Command(BaseCommand):
    help = "Add (or remove) Pro days for one account."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("days", type=int)

    def handle(self, *args, **options):
        if options["days"] < 0 or options["days"] > 3650:
            raise CommandError("days must be between 0 and 3650")
        user = get_user_model().objects.filter(email__iexact=options["email"]).first()
        if user is None:
            raise CommandError("no account with that email")
        acc = _account(user)
        if options["days"] == 0:
            acc.pro_until = None
        else:
            acc.pro_until = max(timezone.now(), acc.pro_until or timezone.now()) + timedelta(days=options["days"])
        acc.save(update_fields=["pro_until"])
        self.stdout.write("%s: Pro until %s" % (user.email, acc.pro_until.isoformat() if acc.pro_until else "off"))
