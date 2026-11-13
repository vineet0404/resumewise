"""Make a demo tailoring run WITHOUT the AI, to try the review and export screens for free.

    python manage.py demo_run <profile_id>

Needs DEBUG=1. It keeps your CV lines, rewords one line with an invented number and adds one
invented line (so you get "new" lines to confirm or remove), and prints the run id.
Never use this in production: the "AI" here is a fixed script.
"""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core import gateway, tailor_service, tailoring

from packs.ai_views import save_run
from packs.models import Profile


class Command(BaseCommand):
    help = "Create a demo run from a profile without calling any AI (DEBUG only)."

    def add_arguments(self, parser):
        parser.add_argument("profile_id")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("demo_run only works with DEBUG=1")
        profile = Profile.objects.filter(id=options["profile_id"]).first()
        if profile is None:
            raise CommandError("no profile with that id")
        parsed = profile.parsed
        sections, invented, total = [], False, 0
        for section in parsed["sections"]:
            if section["key"] == "personal":
                continue  # personal details are never sent to the AI, so the demo leaves them out too
            bullets = []
            for item in section["items"]:
                text, change = item["text"], "kept"
                if total >= tailoring.MAX_BULLETS_TOTAL - 1:  # keep room for the invented line
                    break  # the rules allow only so many lines; a demo does not need more
                if not text.strip() or len(text) > tailoring.MAX_BULLET_CHARS - 40:
                    continue  # too long to add a demo suffix to; skip it in the demo
                if not invented:
                    text, change, invented = text.rstrip(".") + " and improved results by 99%.", "reworded", True
                bullets.append({"text": text, "source_id": item["id"], "change": change, "keywords_used": []})
                total += 1
            if bullets:
                sections.append({"type": section["key"], "bullets": bullets})
        if sections:  # one line that is certainly "new"
            sections[0]["bullets"].append({"text": "Led a team of 12 engineers.", "source_id": None,
                                           "change": "new", "keywords_used": []})
        reply = {"sections": sections, "gaps": [{"requirement": "Example gap", "advice": "This is demo data."}]}
        ids = {i["id"] for sec in parsed["sections"] if sec["key"] != "personal" for i in sec["items"]}
        problems = tailoring.validate_tailoring(reply, ids)
        if problems:
            raise CommandError("the demo reply is not valid for this CV: " + "; ".join(problems[:5]))
        gw = gateway.Gateway({"tailor": gateway.FakeProvider([json.dumps(reply)] * 2)})
        result = tailor_service.tailor(parsed, "Demo job description", gw)
        run = save_run(profile.user, profile, "Demo job description", "Demo", result)
        self.stdout.write("run_id: %s" % run.id)
        self.stdout.write("%d line(s) need your decision." % result["needs_review"])
        self.stdout.write("Next: GET /v1/runs/%s in Postman to see them." % run.id)
