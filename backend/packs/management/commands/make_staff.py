"""Give a person access to the owner dashboard:  python manage.py make_staff you@example.com  (add --remove to undo)."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Make an existing account a staff account (can open the Admin tab). Does not grant Django admin site rights."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--remove", action="store_true")

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username=options["email"].strip().lower()).first()
        if user is None:
            raise CommandError("no account with that email")
        user.is_staff = not options["remove"]
        user.save(update_fields=["is_staff"])
        self.stdout.write("%s is %s" % (user.email, "staff now" if user.is_staff else "not staff any more"))
