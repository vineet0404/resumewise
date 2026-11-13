import os
import time
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from unittest import mock
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from config.dburl import parse_database_url

from .models import Job, Profile, ProfilePhoto

RESUME = """Aarti Sharma

PROJECTS
- Tested 12 web modules and logged 60+ defects.
- Wrote test cases and defect reports for login and payment pages.
"""
JOB = "Required: experience with test cases and defect reporting. Knowledge of Selenium is a plus."


def post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


class DatabaseUrlTests(SimpleTestCase):
    def test_sqlite(self):
        self.assertEqual(parse_database_url("sqlite:///db.sqlite3")["NAME"], "db.sqlite3")
        self.assertEqual(parse_database_url("sqlite://:memory:")["NAME"], ":memory:")

    def test_postgres(self):
        cfg = parse_database_url("postgres://u:p%40ss@db.example:5432/resumewise")
        self.assertEqual(cfg["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual((cfg["USER"], cfg["PASSWORD"], cfg["HOST"], cfg["PORT"], cfg["NAME"]),
                         ("u", "p@ss", "db.example", "5432", "resumewise"))

    def test_oracle_and_mssql(self):
        self.assertEqual(parse_database_url("oracle://u:p@h:1521/XEPDB1")["ENGINE"], "django.db.backends.oracle")
        self.assertEqual(parse_database_url("mssql://u:p@h:1433/db")["ENGINE"], "mssql")

    def test_unknown_scheme_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_database_url("mysql://u:p@h/db")


class ApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.alice = User.objects.create_user("alice", password="a-long-password-1")
        self.bob = User.objects.create_user("bob", password="a-long-password-2")
        self.client = Client()

    def test_health_is_public(self):
        self.assertEqual(self.client.get("/v1/health").json(), {"status": "ok"})

    def test_match_requires_login(self):
        response = post_json(self.client, "/v1/match", {"resume_text": RESUME, "job_text": JOB})
        self.assertEqual(response.status_code, 401)

    def test_match_returns_score_and_gaps(self):
        self.client.force_login(self.alice)
        response = post_json(self.client, "/v1/match", {"resume_text": RESUME, "job_text": JOB})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(0 < body["score"] < 100)
        self.assertIn("selenium", body["missing"])

    def test_bad_input_is_rejected(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.post("/v1/match", data="{oops", content_type="application/json").status_code, 400)
        self.assertEqual(post_json(self.client, "/v1/match", {"resume_text": RESUME}).status_code, 400)
        self.assertEqual(post_json(self.client, "/v1/match", {"resume_text": 5, "job_text": JOB}).status_code, 400)

    @override_settings(MAX_TEXT_CHARS=50)
    def test_oversized_text_is_rejected(self):
        self.client.force_login(self.alice)
        response = post_json(self.client, "/v1/match", {"resume_text": "x" * 51, "job_text": JOB})
        self.assertEqual(response.status_code, 413)

    def test_csrf_is_enforced(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.alice)
        response = post_json(strict, "/v1/match", {"resume_text": RESUME, "job_text": JOB})
        self.assertEqual(response.status_code, 403)

    def test_user_cannot_read_another_users_profile(self):
        self.client.force_login(self.alice)
        created = post_json(self.client, "/v1/profiles", {"resume_text": RESUME})
        self.assertEqual(created.status_code, 201)
        profile_id = created.json()["id"]
        self.assertEqual(self.client.get("/v1/profiles/" + profile_id).status_code, 200)

        other = Client()
        other.force_login(self.bob)
        self.assertEqual(other.get("/v1/profiles/" + profile_id).status_code, 404)
        self.assertEqual(Client().get("/v1/profiles/" + profile_id).status_code, 401)

    def test_profile_gets_an_expiry_date(self):
        self.client.force_login(self.alice)
        post_json(self.client, "/v1/profiles", {"resume_text": RESUME})
        profile = Profile.objects.get()
        self.assertGreater(profile.expires_at, timezone.now() + timedelta(days=29))


class RetentionTests(TestCase):
    def test_purge_removes_only_expired_rows(self):
        user = get_user_model().objects.create_user("carol", password="a-long-password-3")
        past = timezone.now() - timedelta(days=1)
        future = timezone.now() + timedelta(days=5)
        Profile.objects.create(user=user, parsed_json="{}", expires_at=past)
        keep = Profile.objects.create(user=user, parsed_json="{}", expires_at=future)
        Job.objects.create(user=user, title="Old", raw_text="x", requirements_json="[]", expires_at=past)
        call_command("purge_expired", verbosity=0)
        self.assertEqual(list(Profile.objects.all()), [keep])
        self.assertEqual(Job.objects.count(), 0)


class AuthTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client()

    def test_register_login_me_logout_flow(self):
        r = post_json(self.client, "/v1/auth/register", {"email": "Neha@Example.com", "password": "Strong-pass-77x", "accept_terms": True})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["email"], "neha@example.com")
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 200)
        self.assertEqual(post_json(self.client, "/v1/auth/logout", {}).status_code, 200)
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)
        r = post_json(self.client, "/v1/auth/login", {"email": "neha@example.com", "password": "Strong-pass-77x"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 200)

    def test_register_rejects_bad_email_and_weak_password(self):
        self.assertEqual(post_json(self.client, "/v1/auth/register", {"email": "nope", "password": "Strong-pass-77x", "accept_terms": True}).status_code, 400)
        self.assertEqual(post_json(self.client, "/v1/auth/register", {"email": "a@b.co", "password": "12345678", "accept_terms": True}).status_code, 400)
        self.assertEqual(post_json(self.client, "/v1/auth/register", {"email": "a@b.co", "password": "x" * 500, "accept_terms": True}).status_code, 400)

    def test_duplicate_email_is_rejected(self):
        body = {"email": "dup@example.com", "password": "Strong-pass-77x", "accept_terms": True}
        self.assertEqual(post_json(Client(), "/v1/auth/register", body).status_code, 201)
        self.assertEqual(post_json(Client(), "/v1/auth/register", body).status_code, 400)

    def test_wrong_password_is_generic_and_gets_throttled(self):
        get_user_model().objects.create_user("who@example.com", "who@example.com", "Strong-pass-77x")
        for _ in range(5):
            r = post_json(self.client, "/v1/auth/login", {"email": "who@example.com", "password": "bad"})
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json(), {"error": "wrong email or password"})
        r = post_json(self.client, "/v1/auth/login", {"email": "who@example.com", "password": "Strong-pass-77x"})
        self.assertEqual(r.status_code, 429)

    def test_unknown_user_looks_like_wrong_password(self):
        r = post_json(self.client, "/v1/auth/login", {"email": "ghost@example.com", "password": "whatever1"})
        self.assertEqual(r.json(), {"error": "wrong email or password"})

    def test_csrf_endpoint_and_enforcement_on_login(self):
        strict = Client(enforce_csrf_checks=True)
        body = {"email": "x@example.com", "password": "Strong-pass-77x", "accept_terms": True}
        self.assertEqual(post_json(strict, "/v1/auth/register", body).status_code, 403)
        token = strict.get("/v1/auth/csrf").json()["csrf"]
        r = strict.post("/v1/auth/register", data=json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 201)

    def test_login_logout_return_a_fresh_csrf_token(self):
        strict = Client(enforce_csrf_checks=True)
        body = {"email": "t@example.com", "password": "Strong-pass-77x", "accept_terms": True}
        token = strict.get("/v1/auth/csrf").json()["csrf"]
        r = strict.post("/v1/auth/register", data=json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        token = r.json()["csrf"]
        r = strict.post("/v1/auth/logout", data="{}", content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200)
        token = r.json()["csrf"]
        r = strict.post("/v1/auth/login", data=json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200)


class UploadTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("up", password="a-long-password-9")
        self.client = Client()

    def _docx(self):
        import io, zipfile
        W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        body = "<w:p><w:r><w:t>PROJECTS</w:t></w:r></w:p><w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>Wrote test cases</w:t></w:r></w:p>"
        xml = '<w:document xmlns:w="%s"><w:body>%s</w:body></w:document>' % (W, body)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", xml)
        return buf.getvalue()

    def test_upload_requires_login(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        r = self.client.post("/v1/profiles/upload", {"file": SimpleUploadedFile("a.txt", b"hi")})
        self.assertEqual(r.status_code, 401)

    def test_upload_docx_creates_profile(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.user)
        r = self.client.post("/v1/profiles/upload", {"file": SimpleUploadedFile("cv.docx", self._docx())})
        self.assertEqual(r.status_code, 201)
        items = r.json()["parsed"]["sections"][0]["items"]
        self.assertEqual(items[0]["text"], "Wrote test cases")
        self.assertEqual(Profile.objects.count(), 1)

    def test_upload_rejects_missing_pdf_and_junk(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.user)
        self.assertEqual(self.client.post("/v1/profiles/upload", {}).status_code, 400)
        self.assertEqual(self.client.post("/v1/profiles/upload", {"file": SimpleUploadedFile("a.pdf", b"%PDF-1")}).status_code, 400)  # broken PDF
        self.assertEqual(self.client.post("/v1/profiles/upload", {"file": SimpleUploadedFile("a.txt", b"\x00\x01")}).status_code, 400)
        self.assertEqual(Profile.objects.count(), 0)


class UploadPdfTests(TestCase):
    def test_pdf_upload_creates_profile(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from tests.test_extract import make_pdf
        user = get_user_model().objects.create_user("pdfu", password="a-long-password-9")
        self.client.force_login(user)
        pdf = make_pdf(["PROJECTS", "Wrote test cases and defect reports for payment pages"])
        r = self.client.post("/v1/profiles/upload", {"file": SimpleUploadedFile("cv.pdf", pdf)})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Profile.objects.count(), 1)


class ProfileEditApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user("owner", password="a-long-password-1")
        self.other = User.objects.create_user("other", password="a-long-password-2")
        self.client = Client()
        self.client.force_login(self.owner)
        text = "Aarti Sharma\naarti@example.com | +91 98765 43210\n\nPROJECTS\n- Tested 12 web modules\n"
        self.pid = post_json(self.client, "/v1/profiles", {"resume_text": text}).json()["id"]
        self.base = "/v1/profiles/" + self.pid

    def patch(self, path, payload):
        return self.client.patch(self.base + path, data=json.dumps(payload), content_type="application/json")

    def test_get_profile_includes_contact(self):
        body = self.client.get(self.base).json()
        self.assertEqual(body["parsed"]["contact"]["email"], "aarti@example.com")

    def test_update_contact(self):
        r = self.patch("/contact", {"email": "new@example.com", "phone": "+91 99999 11111", "links": ["github.com/aarti"]})
        self.assertEqual(r.status_code, 200)
        contact = self.client.get(self.base).json()["parsed"]["contact"]
        self.assertEqual(contact["email"], "new@example.com")
        self.assertEqual(contact["links"], ["github.com/aarti"])

    def test_bad_contact_is_rejected_and_nothing_saved(self):
        self.assertEqual(self.patch("/contact", {"email": "nope"}).status_code, 400)
        self.assertEqual(Profile.objects.get().versions.count(), 0)

    def test_add_edit_remove_line(self):
        r = post_json(self.client, self.base + "/items", {"section": "experience", "text": "QA Intern at Diebold"})
        self.assertEqual(r.status_code, 201)
        item_id = r.json()["item_id"]
        r = self.patch("/items/" + item_id, {"text": "QA Intern at Diebold, 2025"})
        self.assertEqual(r.status_code, 200)
        r = self.client.delete(self.base + "/items/" + item_id)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.delete(self.base + "/items/" + item_id).status_code, 404)

    def test_add_validation(self):
        self.assertEqual(post_json(self.client, self.base + "/items", {"section": "hobbies", "text": "x"}).status_code, 400)
        self.assertEqual(post_json(self.client, self.base + "/items", {"section": "skills", "text": " "}).status_code, 400)

    def test_undo_with_versions(self):
        post_json(self.client, self.base + "/items", {"section": "skills", "text": "Python"})
        versions = self.client.get(self.base + "/versions").json()["versions"]
        self.assertEqual(len(versions), 1)
        r = self.client.post(self.base + "/versions/%s/restore" % versions[0]["id"])
        self.assertEqual(r.status_code, 200)
        keys = [s["key"] for s in self.client.get(self.base).json()["parsed"]["sections"]]
        self.assertNotIn("skills", keys)
        self.assertEqual(len(self.client.get(self.base + "/versions").json()["versions"]), 2)

    def test_versions_are_capped(self):
        for i in range(25):
            self.patch("/contact", {"phone": "+91 99999 %05d" % i})
        self.assertEqual(Profile.objects.get().versions.count(), 20)

    def test_other_user_gets_404_everywhere_and_anonymous_401(self):
        other = Client()
        other.force_login(self.other)
        ok = lambda r: r.status_code == 404
        self.assertTrue(ok(other.patch(self.base + "/contact", data="{}", content_type="application/json")))
        self.assertTrue(ok(other.post(self.base + "/items", data=json.dumps({"section": "skills", "text": "x"}), content_type="application/json")))
        self.assertTrue(ok(other.delete(self.base + "/items/projects.1")))
        self.assertTrue(ok(other.get(self.base + "/versions")))
        anon = Client()
        self.assertEqual(anon.get(self.base + "/versions").status_code, 401)
        self.assertEqual(anon.delete(self.base + "/items/projects.1").status_code, 401)

    def test_csrf_enforced_on_edits(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.owner)
        r = strict.delete(self.base + "/items/projects.1")
        self.assertEqual(r.status_code, 403)


class TemplateApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user("towner", password="a-long-password-1")
        self.other = User.objects.create_user("tother", password="a-long-password-2")
        self.client = Client()
        self.client.force_login(self.owner)
        text = "Aarti Sharma\naarti@example.com | +91 98765 43210\n\nPROJECTS\n- Tested 12 web modules\n"
        self.pid = post_json(self.client, "/v1/profiles", {"resume_text": text}).json()["id"]
        self.base = "/v1/profiles/" + self.pid

    def photo_file(self, kind="png", **kw):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from tests.test_image_check import make_jpeg, make_png
        if kind == "png":
            return SimpleUploadedFile("me.png", make_png(**kw))
        return SimpleUploadedFile("me.jpg", make_jpeg(**kw))

    def test_list_templates(self):
        body = self.client.get("/v1/templates").json()
        self.assertEqual(len(body["templates"]), 5)
        self.assertEqual(Client().get("/v1/templates").status_code, 401)

    def test_choose_template(self):
        r = self.client.patch(self.base + "/template", data=json.dumps({"template": "modern"}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(self.base).json()["template"], "modern")
        bad = self.client.patch(self.base + "/template", data=json.dumps({"template": "nope"}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)

    def test_photo_upload_render_and_delete(self):
        r = self.client.post(self.base + "/photo", {"photo": self.photo_file("jpg", with_exif=True)})
        self.assertEqual(r.status_code, 201)
        stored = bytes(Profile.objects.get().photo.data)
        self.assertNotIn(b"GPS-LATITUDE", stored)  # location data was stripped
        self.assertTrue(self.client.get(self.base).json()["has_photo"])
        page = self.client.get(self.base + "/render?template=photo_sidebar")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"data:image/jpeg;base64,", page.content)
        self.assertIn("default-src 'none'", page["Content-Security-Policy"])
        plain = self.client.get(self.base + "/render?template=classic")
        self.assertNotIn(b"data:image", plain.content)
        self.assertEqual(self.client.delete(self.base + "/photo").json()["has_photo"], False)
        self.assertFalse(self.client.get(self.base).json()["has_photo"])

    def test_bad_photos_are_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.assertEqual(self.client.post(self.base + "/photo", {}).status_code, 400)
        junk = SimpleUploadedFile("x.png", b"not an image")
        self.assertEqual(self.client.post(self.base + "/photo", {"photo": junk}).status_code, 400)
        svg = SimpleUploadedFile("x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>")
        self.assertEqual(self.client.post(self.base + "/photo", {"photo": svg}).status_code, 400)
        big = SimpleUploadedFile("big.png", b"\\x89PNG" + b"0" * (2 * 1024 * 1024))
        self.assertEqual(self.client.post(self.base + "/photo", {"photo": big}).status_code, 413)
        self.assertEqual(ProfilePhoto.objects.count(), 0)

    def test_render_uses_chosen_template_and_rejects_unknown(self):
        self.client.patch(self.base + "/template", data=json.dumps({"template": "compact"}), content_type="application/json")
        self.assertIn(b"Aarti Sharma", self.client.get(self.base + "/render").content)
        self.assertEqual(self.client.get(self.base + "/render?template=zzz").status_code, 400)

    def test_other_users_cannot_touch_template_photo_or_render(self):
        other = Client()
        other.force_login(self.other)
        self.assertEqual(other.get(self.base + "/render").status_code, 404)
        self.assertEqual(other.delete(self.base + "/photo").status_code, 404)
        self.assertEqual(other.post(self.base + "/photo", {"photo": self.photo_file()}).status_code, 404)
        self.assertEqual(other.patch(self.base + "/template", data=json.dumps({"template": "modern"}), content_type="application/json").status_code, 404)
        self.assertEqual(Client().get(self.base + "/render").status_code, 401)

    def test_photo_is_deleted_with_expired_profile(self):
        self.client.post(self.base + "/photo", {"photo": self.photo_file()})
        Profile.objects.update(expires_at=timezone.now() - timedelta(days=1))
        call_command("purge_expired", verbosity=0)
        self.assertEqual(ProfilePhoto.objects.count(), 0)


class ContactLocationApiTests(TestCase):
    def test_location_is_guessed_and_editable(self):
        user = get_user_model().objects.create_user("loc", password="a-long-password-1")
        c = Client()
        c.force_login(user)
        text = "Aarti Sharma\nMumbai, Maharashtra | aarti@example.com | linkedin.com/in/aarti\n\nPROJECTS\n- Tested modules\n"
        pid = post_json(c, "/v1/profiles", {"resume_text": text}).json()["id"]
        contact = c.get("/v1/profiles/" + pid).json()["parsed"]["contact"]
        self.assertEqual(contact["location"], "Mumbai, Maharashtra")
        self.assertEqual(contact["links"], ["linkedin.com/in/aarti"])
        r = c.patch("/v1/profiles/%s/contact" % pid, data=json.dumps({"location": "Pune, Maharashtra"}), content_type="application/json")
        self.assertEqual(r.json()["contact"]["location"], "Pune, Maharashtra")


class AtsApiTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("atsu", password="a-long-password-1")
        self.other = get_user_model().objects.create_user("atso", password="a-long-password-2")
        self.client = Client()
        self.client.force_login(user)
        text = ("Aarti Sharma\nMumbai, Maharashtra | aarti@example.com | +91 98765 43210\n\n"
                "EXPERIENCE\n- QA Intern, Finserve (2025)\n\nSKILLS\n- Jira, Postman\n\nEDUCATION\n- MCA, Mumbai, 2026\n")
        self.pid = post_json(self.client, "/v1/profiles", {"resume_text": text}).json()["id"]

    def test_ats_for_each_template(self):
        for tid in ("classic", "modern", "compact", "photo_header", "photo_sidebar"):
            body = self.client.get("/v1/profiles/%s/ats?template=%s" % (self.pid, tid)).json()
            self.assertGreaterEqual(body["score"], 90, tid)
            self.assertEqual(body["template"], tid)
        self.assertIn("not a real company", body["note"])

    def test_ats_unknown_template_and_other_user(self):
        self.assertEqual(self.client.get("/v1/profiles/%s/ats?template=zzz" % self.pid).status_code, 400)
        other = Client()
        other.force_login(self.other)
        self.assertEqual(other.get("/v1/profiles/%s/ats" % self.pid).status_code, 404)
        self.assertEqual(Client().get("/v1/profiles/%s/ats" % self.pid).status_code, 401)

    def test_upload_reports_ats_for_the_file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        spaced = b"Aarti Sharma\naarti@example.com | +91 98765 43210\n\nE X P E R I E N C E\n- Tested modules 2025\n"
        r = self.client.post("/v1/profiles/upload", {"file": SimpleUploadedFile("cv.txt", spaced)})
        codes = [f["code"] for f in r.json()["ats"]["findings"]]
        self.assertIn("spaced_headings", codes)


class ExportApiTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("expu", password="a-long-password-1")
        self.other = get_user_model().objects.create_user("expo", password="a-long-password-2")
        self.client = Client()
        self.client.force_login(user)
        text = "Aarti <b>Sharma</b>\naarti@example.com\n\nEXPERIENCE\n- Tested R&D modules 2025\n"
        self.pid = post_json(self.client, "/v1/profiles", {"resume_text": text}).json()["id"]

    def test_download_docx_round_trips_and_escapes(self):
        from core import extract
        r = self.client.get("/v1/profiles/%s/export?format=docx" % self.pid)
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        text = extract.extract_text("resume.docx", r.content)
        self.assertIn("Aarti <b>Sharma</b>", text)
        self.assertIn("Tested R&D modules 2025", text)

    def test_export_rejects_other_format_other_user_and_anonymous(self):
        self.assertEqual(self.client.get("/v1/profiles/%s/export?format=exe" % self.pid).status_code, 400)
        other = Client()
        other.force_login(self.other)
        self.assertEqual(other.get("/v1/profiles/%s/export" % self.pid).status_code, 404)
        self.assertEqual(Client().get("/v1/profiles/%s/export" % self.pid).status_code, 401)


class TailorApiTests(TestCase):
    TEXT = ("Aarti Sharma\naarti@example.com\n\nPROJECTS\n- Built a bus booking system with Python and Django.\n"
            "- Wrote 45 test cases.\n")

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        user = get_user_model().objects.create_user("tailu", password="a-long-password-1")
        self.other = get_user_model().objects.create_user("tailo", password="a-long-password-2")
        self.client = Client()
        self.client.force_login(user)
        self.pid = post_json(self.client, "/v1/profiles", {"resume_text": self.TEXT}).json()["id"]

    def _gateway(self, reply):
        from core import gateway as gw
        self.fake = gw.FakeProvider([json.dumps(reply)] if isinstance(reply, dict) else [reply] * 3)
        return lambda: gw.Gateway({"tailor": self.fake})

    GOOD = {"sections": [{"type": "projects", "bullets": [
        {"text": "Built a bus booking system with Python and Django.", "source_id": "projects.1", "change": "kept", "keywords_used": []},
        {"text": "Wrote 99 test cases.", "source_id": "projects.2", "change": "reworded", "keywords_used": []}]}],
        "gaps": []}

    def test_tailor_checks_labels_stores_and_hides_personal_details(self):
        from unittest import mock
        with mock.patch("packs.ai_views.build_gateway", self._gateway(self.GOOD)):
            r = post_json(self.client, "/v1/profiles/%s/tailor" % self.pid, {"job_text": "Need Django. Mail hr@corp.com"})
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual([c["label"] for c in body["claims"]], ["supported", "new"])
        self.assertEqual(body["needs_review"], 1)
        sent = self.fake.calls[0]["user"].lower()
        self.assertNotIn("aarti", sent)
        self.assertNotIn("hr@corp.com", sent)
        from packs.models import Claim, Run
        self.assertEqual(Run.objects.get().status, "needs_review")
        self.assertEqual(Claim.objects.count(), 2)

    def test_not_configured_other_user_anonymous_and_limits(self):
        url = "/v1/profiles/%s/tailor" % self.pid
        with self.settings():
            import os
            os.environ.pop("ANTHROPIC_API_KEY", None)
            self.assertEqual(post_json(self.client, url, {"job_text": "x"}).status_code, 503)
        other = Client()
        other.force_login(self.other)
        self.assertEqual(post_json(other, url, {"job_text": "x"}).status_code, 404)
        self.assertEqual(Client().post(url, "{}", content_type="application/json").status_code, 401)
        self.assertEqual(post_json(self.client, url, {"job_text": "x" * 9000}).status_code, 413)

    def test_bad_ai_reply_gives_safe_error_and_stores_nothing(self):
        from unittest import mock
        from packs.models import Run
        with mock.patch("packs.ai_views.build_gateway", self._gateway("not json at all")):
            r = post_json(self.client, "/v1/profiles/%s/tailor" % self.pid, {"job_text": "Need Django"})
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("not json", r.content.decode())
        self.assertEqual(Run.objects.count(), 0)

    def test_rate_limit(self):
        from unittest import mock
        url = "/v1/profiles/%s/tailor" % self.pid
        statuses = []
        with mock.patch("packs.ai_views.build_gateway", lambda: self._gateway("bad")()):
            for _ in range(12):
                statuses.append(post_json(self.client, url, {"job_text": "Need Django"}).status_code)
        self.assertEqual(statuses[-1], 429)


class TailorKeyMessageTests(TestCase):
    def test_placeholder_key_gets_a_clear_503(self):
        import os
        from unittest import mock
        user = get_user_model().objects.create_user("keyu", password="a-long-password-1")
        c = Client(); c.force_login(user)
        pid = post_json(c, "/v1/profiles", {"resume_text": "A\n\nSKILLS\n- Jira\n"}).json()["id"]
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "teri-key-yahan"}):
            r = post_json(c, "/v1/profiles/%s/tailor" % pid, {"job_text": "Need Jira"})
        self.assertEqual(r.status_code, 503)
        self.assertIn("does not look like a real key", r.json()["error"])
        self.assertNotIn("teri-key", r.content.decode())


class RunReviewApiTests(TestCase):
    TEXT = ("Aarti Sharma\naarti@example.com | +91 98765 43210\n\nPROJECTS\n- Built a bus booking system with Python and Django.\n"
            "- Wrote 45 test cases.\n\nSKILLS\n- Jira, Postman\n")
    REPLY = {"sections": [{"type": "projects", "bullets": [
        {"text": "Built a bus booking system with Python and Django.", "source_id": "projects.1", "change": "kept", "keywords_used": []},
        {"text": "Wrote 99 test cases.", "source_id": "projects.2", "change": "reworded", "keywords_used": []}]},
        {"type": "skills", "bullets": [{"text": "Jira, Postman", "source_id": "skills.1", "change": "kept", "keywords_used": []}]}],
        "gaps": [{"requirement": "Postgres", "advice": "Learn it."}]}

    def setUp(self):
        from unittest import mock
        from core import gateway as gw
        from django.core.cache import cache
        cache.clear()
        user = get_user_model().objects.create_user("runu", password="a-long-password-1")
        self.other = get_user_model().objects.create_user("runo", password="a-long-password-2")
        self.client = Client(); self.client.force_login(user)
        self.pid = post_json(self.client, "/v1/profiles", {"resume_text": self.TEXT}).json()["id"]
        fake = gw.FakeProvider([json.dumps(self.REPLY)])
        with mock.patch("packs.ai_views.build_gateway", lambda: gw.Gateway({"tailor": fake})):
            body = post_json(self.client, "/v1/profiles/%s/tailor" % self.pid, {"job_text": "Need Django"}).json()
        self.run_id = body["run_id"]

    def test_detail_shows_lines_labels_reasons_and_blocks_export(self):
        d = self.client.get("/v1/runs/%s" % self.run_id).json()
        self.assertEqual([l["label"] for l in d["lines"]], ["supported", "new", "supported"])
        self.assertIn("number not in the original", d["lines"][1]["reason"])
        self.assertEqual(d["pending"], ["s0.b1"])
        self.assertFalse(d["can_export"])
        for kind in ("export?format=docx", "render", "ats"):
            r = self.client.get("/v1/runs/%s/%s" % (self.run_id, kind))
            self.assertEqual(r.status_code, 409, kind)
            self.assertEqual(r.json()["pending"], ["s0.b1"])

    def test_remove_new_line_then_export_has_no_fake_number_and_keeps_contact(self):
        from core import extract
        r = self.client.patch("/v1/runs/%s/claims/s0.b1" % self.run_id, json.dumps({"decision": "removed"}),
                              content_type="application/json")
        self.assertEqual(r.json()["can_export"], True)
        from packs.models import Run
        self.assertEqual(Run.objects.get().status, "ready")
        docx = self.client.get("/v1/runs/%s/export?format=docx" % self.run_id)
        self.assertEqual(docx.status_code, 200)
        text = extract.extract_text("t.docx", docx.content)
        self.assertNotIn("99 test cases", text)
        self.assertIn("Built a bus booking system", text)
        self.assertIn("aarti@example.com", text)
        html = self.client.get("/v1/runs/%s/render?template=modern" % self.run_id).content.decode()
        self.assertNotIn("99 test cases", html)
        ats = self.client.get("/v1/runs/%s/ats" % self.run_id).json()
        self.assertGreaterEqual(ats["score"], 85)

    def test_confirm_keeps_line_and_decision_can_be_changed(self):
        patch = lambda d: self.client.patch("/v1/runs/%s/claims/s0.b1" % self.run_id, json.dumps({"decision": d}),
                                            content_type="application/json")
        self.assertTrue(patch("confirmed").json()["can_export"])
        html = self.client.get("/v1/runs/%s/render" % self.run_id).content.decode()
        self.assertIn("99 test cases", html)
        self.assertFalse(patch("pending").json()["can_export"])
        self.assertEqual(patch("maybe").status_code, 400)

    def test_other_user_and_anonymous_cannot_touch_it(self):
        other = Client(); other.force_login(self.other)
        base = "/v1/runs/%s" % self.run_id
        self.assertEqual(other.get(base).status_code, 404)
        self.assertEqual(other.patch(base + "/claims/s0.b1", json.dumps({"decision": "removed"}),
                                     content_type="application/json").status_code, 404)
        for kind in ("render", "ats", "export"):
            self.assertEqual(other.get("%s/%s" % (base, kind)).status_code, 404)
        self.assertEqual(Client().get(base).status_code, 401)
        self.assertEqual(self.client.get("/v1/runs/%s" % "00000000-0000-0000-0000-000000000000").status_code, 404)
        self.assertEqual(self.client.patch(base + "/claims/nope", json.dumps({"decision": "removed"}),
                                           content_type="application/json").status_code, 404)


class DemoRunCommandTests(TestCase):
    def test_demo_run_makes_a_reviewable_run_only_in_debug(self):
        from io import StringIO
        from django.core.management import CommandError
        user = get_user_model().objects.create_user("demou", password="a-long-password-1")
        c = Client(); c.force_login(user)
        pid = post_json(c, "/v1/profiles", {"resume_text": "A B\n\nEXPERIENCE\n- Tested modules in 2025.\n\nSKILLS\n- Jira\n"}).json()["id"]
        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                call_command("demo_run", pid)
        out = StringIO()
        with override_settings(DEBUG=True):
            call_command("demo_run", pid, stdout=out)
        run_id = out.getvalue().split("run_id: ")[1].split()[0]
        d = c.get("/v1/runs/%s" % run_id).json()
        self.assertEqual(len(d["pending"]), 2)  # the invented number and the invented line
        self.assertFalse(d["can_export"])


class DemoRunBigCvTests(TestCase):
    def test_demo_run_handles_a_long_cv_with_long_lines(self):
        from io import StringIO
        user = get_user_model().objects.create_user("bigu", password="a-long-password-1")
        c = Client(); c.force_login(user)
        lines = ["- Tested module %d in 2025." % i for i in range(80)] + ["- " + "long " * 120]
        text = "A B\n\nEXPERIENCE\n" + "\n".join(lines) + "\n\nSKILLS\n- Jira\n"
        pid = post_json(c, "/v1/profiles", {"resume_text": text}).json()["id"]
        out = StringIO()
        with override_settings(DEBUG=True):
            call_command("demo_run", pid, stdout=out)
        self.assertIn("run_id:", out.getvalue())
        self.assertIn("2 line(s) need your decision", out.getvalue())

    def test_demo_run_gives_new_lines_even_when_there_is_no_experience_section(self):
        from io import StringIO
        user = get_user_model().objects.create_user("bigu2", password="a-long-password-1")
        c = Client(); c.force_login(user)
        pid = post_json(c, "/v1/profiles", {"resume_text": "A B\n\nSKILLS\n- Jira\n- SQL\n"}).json()["id"]
        out = StringIO()
        with override_settings(DEBUG=True):
            call_command("demo_run", pid, stdout=out)
        self.assertNotIn("0 line(s)", out.getvalue())


class NameEditApiTests(TestCase):
    def test_name_is_guessed_and_can_be_edited(self):
        user = get_user_model().objects.create_user("nameu", password="a-long-password-1")
        c = Client(); c.force_login(user)
        text = "Institute Address: Thakur Institute, Mumbai\nVineet Singh\nv@example.com\n\nSKILLS\n- Python\n"
        pid = post_json(c, "/v1/profiles", {"resume_text": text}).json()["id"]
        got = c.get("/v1/profiles/%s" % pid).json()["parsed"]["contact"]
        self.assertEqual(got["name"], "Vineet Singh")
        r = c.patch("/v1/profiles/%s/contact" % pid, json.dumps({"name": "Vineet K Singh"}), content_type="application/json")
        self.assertEqual(r.json()["contact"]["name"], "Vineet K Singh")
        html = c.get("/v1/profiles/%s/render?template=classic" % pid).content.decode()
        self.assertIn("<h1>Vineet K Singh</h1>", html)
        bad = c.patch("/v1/profiles/%s/contact" % pid, json.dumps({"name": "x" * 200}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)


class AccountDataApiTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("acct", password="a-long-password-1")
        self.other = get_user_model().objects.create_user("acct2", password="a-long-password-2")
        self.client = Client(); self.client.force_login(user)

    def test_list_open_and_delete_my_cvs_only(self):
        a = post_json(self.client, "/v1/profiles", {"resume_text": "Aarti Sharma\n\nSKILLS\n- Jira\n"}).json()["id"]
        other = Client(); other.force_login(self.other)
        b = post_json(other, "/v1/profiles", {"resume_text": "Raj Patel\n\nSKILLS\n- SQL\n"}).json()["id"]
        listed = self.client.get("/v1/profiles").json()["profiles"]
        self.assertEqual([p["id"] for p in listed], [a])
        self.assertEqual(listed[0]["name"], "Aarti Sharma")
        self.assertEqual(self.client.get("/v1/profiles/%s" % a).status_code, 200)
        self.assertEqual(self.client.delete("/v1/profiles/%s" % b).status_code, 404)  # not mine
        self.assertEqual(other.get("/v1/profiles/%s" % b).status_code, 200)            # still there
        self.assertEqual(Client().get("/v1/profiles").status_code, 401)

    def test_delete_removes_runs_jobs_and_everything_under_it(self):
        from unittest import mock
        from core import gateway as gw
        from packs.models import Job, Profile, Run
        pid = post_json(self.client, "/v1/profiles", {"resume_text": "A B\n\nPROJECTS\n- Built a site.\n"}).json()["id"]
        reply = json.dumps({"sections": [{"type": "projects", "bullets": [
            {"text": "Built a site.", "source_id": "projects.1", "change": "kept", "keywords_used": []}]}], "gaps": []})
        fake = gw.FakeProvider([reply])
        with mock.patch("packs.ai_views.build_gateway", lambda: gw.Gateway({"tailor": fake})):
            run_id = post_json(self.client, "/v1/profiles/%s/tailor" % pid, {"job_text": "Need sites", "job_title": "Dev"}).json()["run_id"]
        runs = self.client.get("/v1/profiles/%s/runs" % pid).json()["runs"]
        self.assertEqual([r["id"] for r in runs], [run_id])
        self.assertEqual(runs[0]["job_title"], "Dev")
        self.assertEqual(self.client.delete("/v1/profiles/%s" % pid).json(), {"status": "deleted"})
        self.assertEqual((Profile.objects.count(), Run.objects.count(), Job.objects.count()), (0, 0, 0))
        self.assertEqual(self.client.get("/v1/runs/%s" % run_id).status_code, 404)


class WebAppTests(TestCase):
    def test_page_and_assets_are_served_with_strict_headers(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("script-src 'self'", r["Content-Security-Policy"])
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertIn(b"/app/app.js", r.content)
        for name, kind in (("app.js", "javascript"), ("app.css", "css")):
            a = self.client.get("/app/" + name)
            self.assertEqual(a.status_code, 200)
            self.assertIn(kind, a["Content-Type"])

    def test_nothing_else_can_be_read_through_the_asset_route(self):
        for bad in ("../settings.py", "..%2Fsettings.py", "manage.py", "app.js.map", "index.htm"):
            self.assertEqual(self.client.get("/app/" + bad).status_code, 404, bad)

    def test_script_never_uses_innerhtml_or_eval(self):
        from packs.web_views import WEB_DIR
        js = (WEB_DIR / "app.js").read_text()
        for banned in ("innerHTML", "outerHTML", "eval(", "document.write", "insertAdjacentHTML"):
            self.assertNotIn(banned, js)


class DemoRunPersonalDetailsTests(TestCase):
    def test_demo_run_works_on_a_cv_with_personal_details(self):
        from io import StringIO
        user = get_user_model().objects.create_user("persu", password="a-long-password-1")
        c = Client(); c.force_login(user)
        text = "A B\n\nPROJECTS\n- Built a site.\n\nABOUT ME\nDate of Birth: 04/04/2001\nGender: Male\n"
        pid = post_json(c, "/v1/profiles", {"resume_text": text}).json()["id"]
        out = StringIO()
        with override_settings(DEBUG=True):
            call_command("demo_run", pid, stdout=out)
        self.assertIn("run_id:", out.getvalue())


class SignInExtrasTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client()
        self.good = "Strong-pass-77x"

    def _register(self, **extra):
        body = {"email": "ria@example.com", "password": self.good, "accept_terms": True}
        body.update(extra)
        r = post_json(self.client, "/v1/auth/register", body)
        from django.core import mail
        mail.outbox.clear()  # sign-up sends a "confirm your email" mail; these tests count other mails
        return r

    def test_terms_must_be_accepted(self):
        r = post_json(self.client, "/v1/auth/register", {"email": "a@b.co", "password": self.good})
        self.assertEqual(r.status_code, 400)
        self.assertIn("terms", r.json()["error"])
        r = post_json(self.client, "/v1/auth/register", {"email": "a@b.co", "password": self.good, "accept_terms": "yes"})
        self.assertEqual(r.status_code, 400)

    def test_name_is_saved_and_returned(self):
        r = self._register(name="  Ria   Sharma ")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["name"], "Ria Sharma")
        self.assertEqual(self.client.get("/v1/auth/me").json()["name"], "Ria Sharma")
        self.assertEqual(self._register(name="x" * 200).status_code, 400)

    def test_remember_me_controls_session_length(self):
        self._register()
        post_json(self.client, "/v1/auth/logout", {})
        post_json(self.client, "/v1/auth/login", {"email": "ria@example.com", "password": self.good, "remember": False})
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        post_json(self.client, "/v1/auth/logout", {})
        post_json(self.client, "/v1/auth/login", {"email": "ria@example.com", "password": self.good, "remember": True})
        self.assertFalse(self.client.session.get_expire_at_browser_close())
        self.assertGreater(self.client.session.get_expiry_age(), 29 * 24 * 3600)

    def _link(self):
        import re
        from django.core import mail
        body = mail.outbox[-1].body
        m = re.search(r"#reset=([^\s.]+)\.(\S+)", body)
        return m.group(1), m.group(2)

    def test_forgot_then_reset_flow(self):
        from django.core import mail
        self._register(name="Ria")
        post_json(self.client, "/v1/auth/logout", {})
        r = post_json(self.client, "/v1/auth/forgot", {"email": "ria@example.com"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Hi Ria", mail.outbox[0].body)
        uid, token = self._link()
        weak = post_json(self.client, "/v1/auth/reset", {"uid": uid, "token": token, "password": "12345678"})
        self.assertEqual(weak.status_code, 400)
        ok = post_json(self.client, "/v1/auth/reset", {"uid": uid, "token": token, "password": "Brand-new-pass-91"})
        self.assertEqual(ok.status_code, 200)
        again = post_json(self.client, "/v1/auth/reset", {"uid": uid, "token": token, "password": "Another-pass-92x"})
        self.assertEqual(again.status_code, 400)  # one-time link
        bad = post_json(self.client, "/v1/auth/login", {"email": "ria@example.com", "password": self.good})
        self.assertEqual(bad.status_code, 401)
        good = post_json(self.client, "/v1/auth/login", {"email": "ria@example.com", "password": "Brand-new-pass-91"})
        self.assertEqual(good.status_code, 200)

    def test_forgot_does_not_reveal_whether_email_exists(self):
        from django.core import mail
        known = self._register()
        post_json(self.client, "/v1/auth/logout", {})
        a = post_json(self.client, "/v1/auth/forgot", {"email": "ria@example.com"})
        b = post_json(self.client, "/v1/auth/forgot", {"email": "nobody@example.com"})
        c = post_json(self.client, "/v1/auth/forgot", {"email": "not an email"})
        self.assertEqual(a.json(), b.json())
        self.assertEqual(b.json(), c.json())
        self.assertEqual(len(mail.outbox), 1)

    def test_forgot_is_limited_per_email(self):
        from django.core import mail
        self._register()
        for _ in range(6):
            post_json(self.client, "/v1/auth/forgot", {"email": "ria@example.com"})
        self.assertEqual(len(mail.outbox), 3)

    def test_reset_rejects_garbage_and_tampered_tokens(self):
        self._register()
        post_json(self.client, "/v1/auth/logout", {})
        post_json(self.client, "/v1/auth/forgot", {"email": "ria@example.com"})
        uid, token = self._link()
        for u, t in (("!!", token), (uid, token + "x"), ("Mg", token), (uid, "")):
            r = post_json(self.client, "/v1/auth/reset", {"uid": u, "token": t, "password": "Brand-new-pass-91"})
            self.assertEqual(r.status_code, 400, (u, t))

    def test_reset_unlocks_a_throttled_account(self):
        self._register()
        post_json(self.client, "/v1/auth/logout", {})
        for _ in range(5):
            post_json(self.client, "/v1/auth/login", {"email": "ria@example.com", "password": "bad"})
        post_json(self.client, "/v1/auth/forgot", {"email": "ria@example.com"})
        uid, token = self._link()
        post_json(self.client, "/v1/auth/reset", {"uid": uid, "token": token, "password": "Brand-new-pass-91"})
        from packs import throttle
        throttle.clear("login-ip", "127.0.0.1")  # the test client shares one IP; only the email lock is under test
        r = post_json(self.client, "/v1/auth/login", {"email": "ria@example.com", "password": "Brand-new-pass-91"})
        self.assertEqual(r.status_code, 200)


class GoogleSignInTests(TestCase):
    """Uses a small fake 'Google' token server on localhost; nothing reaches the real Google."""

    PROVIDER = "google"
    ISS = "https://accounts.google.com"
    BAD_ISS = "https://evil.example"
    CLIENT = "client-123.apps.googleusercontent.com"
    reply_claims = {}

    @classmethod
    def setUpClass(cls):
        import base64, threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        outer = cls

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                seg = base64.urlsafe_b64encode(json.dumps(outer.reply_claims).encode()).decode().rstrip("=")
                data = json.dumps({"id_token": "x.%s.y" % seg}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        super().tearDownClass()

    def setUp(self):
        from django.core.cache import cache
        from django.test import override_settings
        cache.clear()
        up = self.PROVIDER.upper()
        ov = override_settings(**{up + "_CLIENT_ID": self.CLIENT, up + "_CLIENT_SECRET": "secret",
                                  up + "_TOKEN_URL": "http://127.0.0.1:%d/token" % self.server.server_port})
        ov.enable()
        self.addCleanup(ov.disable)
        self.client = Client()

    def _begin(self):
        import urllib.parse
        r = self.client.get("/v1/auth/%s/start" % self.PROVIDER)
        self.assertEqual(r.status_code, 302)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(r["Location"]).query)
        self.assertEqual(q["client_id"], [self.CLIENT])
        self.assertEqual(q["scope"], ["openid email profile"])
        return q["state"][0], q["nonce"][0]

    def _claims(self, real_nonce, **over):
        c = {"aud": self.CLIENT, "iss": self.ISS, "exp": time.time() + 600,
             "email": "Gita@Gmail.com", "email_verified": True, "name": "Gita Rao", "nonce": real_nonce}
        c.update(over)
        type(self).reply_claims = c

    def test_providers_flag_and_off_when_not_configured(self):
        self.assertTrue(self.client.get("/v1/auth/providers").json()[self.PROVIDER])
        from django.test import override_settings
        with override_settings(**{self.PROVIDER.upper() + "_CLIENT_ID": ""}):
            self.assertFalse(self.client.get("/v1/auth/providers").json()[self.PROVIDER])
            self.assertEqual(self.client.get("/v1/auth/%s/start" % self.PROVIDER).status_code, 404)
            self.assertEqual(self.client.get("/v1/auth/%s/callback?code=a&state=b" % self.PROVIDER).status_code, 404)

    def test_new_user_is_created_and_signed_in(self):
        state, nonce = self._begin()
        self._claims(nonce)
        r = self.client.get("/v1/auth/%s/callback" % self.PROVIDER, {"code": "c", "state": state})
        self.assertEqual((r.status_code, r["Location"]), (302, "/"))
        me = self.client.get("/v1/auth/me").json()
        self.assertEqual((me["email"], me["name"]), ("gita@gmail.com", "Gita Rao"))
        self.assertFalse(get_user_model().objects.get(username="gita@gmail.com").has_usable_password())

    def test_existing_account_with_same_email_is_reused(self):
        get_user_model().objects.create_user("gita@gmail.com", "gita@gmail.com", "Strong-pass-77x")
        state, nonce = self._begin()
        self._claims(nonce)
        self.client.get("/v1/auth/%s/callback" % self.PROVIDER, {"code": "c", "state": state})
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 200)

    def _assert_rejected(self, r):
        self.assertEqual(r["Location"], "/#signin=failed")
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_wrong_state_is_rejected(self):
        state, nonce = self._begin()
        self._claims(nonce)
        self._assert_rejected(self.client.get("/v1/auth/%s/callback" % self.PROVIDER, {"code": "c", "state": "forged"}))

    def test_state_cannot_be_replayed(self):
        state, nonce = self._begin()
        self._claims(nonce)
        self.client.get("/v1/auth/%s/callback" % self.PROVIDER, {"code": "c", "state": state})
        post_json(self.client, "/v1/auth/logout", {})
        r = self.client.get("/v1/auth/%s/callback" % self.PROVIDER, {"code": "c", "state": state})
        self.assertEqual(r["Location"], "/#signin=failed")

    def test_bad_tokens_are_rejected(self):
        for over in ({"aud": "someone-else"}, {"iss": self.BAD_ISS}, {"exp": time.time() - 5},
                     {"email_verified": False}, {"nonce": "other"}, {"email": "no-at-sign"}):
            self.client = Client()
            state, nonce = self._begin()
            self._claims(nonce, **over)
            self._assert_rejected(self.client.get("/v1/auth/%s/callback" % self.PROVIDER, {"code": "c", "state": state}))

    def test_user_pressing_cancel(self):
        self._begin()
        r = self.client.get("/v1/auth/%s/callback" % self.PROVIDER, {"error": "access_denied", "state": "x"})
        self.assertEqual(r["Location"], "/#signin=denied")

    def test_unreachable_google_fails_safely(self):
        from django.test import override_settings
        state, nonce = self._begin()
        with override_settings(**{self.PROVIDER.upper() + "_TOKEN_URL": "http://127.0.0.1:9/token"}):
            self._assert_rejected(self.client.get("/v1/auth/%s/callback" % self.PROVIDER, {"code": "c", "state": state}))

    def test_new_provider_user_is_marked_email_verified(self):
        state, nonce = self._begin()
        self._claims(nonce)
        self.client.get("/v1/auth/%s/callback" % self.PROVIDER, {"code": "c", "state": state})
        self.assertTrue(self.client.get("/v1/auth/me").json()["email_verified"])

    def test_provider_login_still_asks_for_2fa_when_on(self):
        from .models import Account
        user = get_user_model().objects.create_user("gita@gmail.com", "gita@gmail.com", "Strong-pass-77x")
        Account.objects.create(user=user, totp_enabled=True, totp_secret="x")
        state, nonce = self._begin()
        self._claims(nonce)
        r = self.client.get("/v1/auth/%s/callback" % self.PROVIDER, {"code": "c", "state": state})
        self.assertEqual(r["Location"], "/#signin=2fa")
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)

    def test_unknown_provider_is_404(self):
        self.assertEqual(self.client.get("/v1/auth/facebook/start").status_code, 404)


class LinkedInSignInTests(GoogleSignInTests):
    PROVIDER = "linkedin"
    ISS = "https://www.linkedin.com/oauth"
    CLIENT = "li-client-77"


class VerifyMagicTwoFactorTests(TestCase):
    PW = "Strong-pass-77x"

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client()

    def _register(self):
        r = post_json(self.client, "/v1/auth/register", {"email": "ria@example.com", "password": self.PW, "accept_terms": True})
        self.assertEqual(r.status_code, 201)
        return r

    def _token(self, kind):
        import re
        from django.core import mail
        m = re.search(r"#%s=(\S+)" % kind, mail.outbox[-1].body)
        return m.group(1)

    # ----- verify email -----
    def test_signup_sends_link_and_it_confirms_once(self):
        from django.core import mail
        r = self._register()
        self.assertFalse(r.json()["email_verified"])
        self.assertEqual(len(mail.outbox), 1)
        token = self._token("verify")
        self.assertEqual(post_json(Client(), "/v1/auth/verify", {"token": token}).status_code, 200)  # works from any browser
        self.assertTrue(self.client.get("/v1/auth/me").json()["email_verified"])
        self.assertEqual(post_json(Client(), "/v1/auth/verify", {"token": token}).status_code, 400)  # one time

    def test_bad_expired_and_wrong_purpose_tokens(self):
        from datetime import timedelta
        from django.utils import timezone
        from .models import EmailToken
        self._register()
        token = self._token("verify")
        for bad in ("", "x" * 40, token + "a", None):
            self.assertEqual(post_json(Client(), "/v1/auth/verify", {"token": bad}).status_code, 400)
        self.assertEqual(post_json(Client(), "/v1/auth/magic", {"token": token}).status_code, 400)  # verify token is not a login token
        EmailToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(post_json(Client(), "/v1/auth/verify", {"token": token}).status_code, 400)

    def test_only_a_hash_is_stored(self):
        from .models import EmailToken
        self._register()
        self.assertNotIn(self._token("verify"), EmailToken.objects.get().token_hash)

    def test_resend_is_limited_and_new_link_replaces_old(self):
        from django.core import mail
        self._register()
        first = self._token("verify")
        for _ in range(3):
            self.assertEqual(post_json(self.client, "/v1/auth/verify/send", {}).status_code, 200)
        self.assertEqual(post_json(self.client, "/v1/auth/verify/send", {}).status_code, 429)
        self.assertEqual(post_json(Client(), "/v1/auth/verify", {"token": first}).status_code, 400)
        self.assertEqual(post_json(Client(), "/v1/auth/verify", {"token": self._token("verify")}).status_code, 200)

    def test_unverified_cannot_use_ai_but_old_accounts_can(self):
        self._register()
        pid = post_json(self.client, "/v1/profiles", {"resume_text": RESUME}).json()["id"]
        r = post_json(self.client, "/v1/profiles/%s/tailor" % pid, {"job_text": "Need Django"})
        self.assertEqual((r.status_code, r.json()["code"]), (403, "email_not_verified"))
        post_json(Client(), "/v1/auth/verify", {"token": self._token("verify")})
        r = post_json(self.client, "/v1/profiles/%s/tailor" % pid, {"job_text": "Need Django"})
        self.assertNotEqual(r.status_code, 403)  # now it gets as far as "AI not set up"

    # ----- magic link -----
    def test_magic_link_logs_in_once_and_verifies_email(self):
        self._register()
        post_json(self.client, "/v1/auth/logout", {})
        other = Client()
        self.assertEqual(post_json(other, "/v1/auth/magic/send", {"email": "ria@example.com"}).status_code, 200)
        token = self._token("magic")
        r = post_json(other, "/v1/auth/magic", {"token": token})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["email_verified"])
        self.assertEqual(other.get("/v1/auth/me").status_code, 200)
        self.assertEqual(post_json(Client(), "/v1/auth/magic", {"token": token}).status_code, 400)

    def test_magic_send_never_reveals_accounts_and_is_limited(self):
        from django.core import mail
        self._register()
        mail.outbox.clear()
        a = post_json(self.client, "/v1/auth/magic/send", {"email": "ria@example.com"})
        b = post_json(self.client, "/v1/auth/magic/send", {"email": "ghost@example.com"})
        self.assertEqual(a.json(), b.json())
        self.assertEqual(len(mail.outbox), 1)
        for _ in range(5):
            post_json(self.client, "/v1/auth/magic/send", {"email": "ria@example.com"})
        self.assertEqual(len(mail.outbox), 3)

    # ----- authenticator app -----
    def _enable_2fa(self):
        from . import totp
        self._register()
        secret = post_json(self.client, "/v1/auth/2fa/setup", {}).json()["secret"]
        r = post_json(self.client, "/v1/auth/2fa/enable", {"code": totp.code_at(secret)})
        self.assertEqual(r.status_code, 200)
        return secret, r.json()["recovery_codes"]

    def test_rfc6238_vectors(self):
        from . import totp
        import base64
        key = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
        self.assertEqual(totp.hotp(totp._key(key), 59 // 30, 8), "94287082")  # RFC 6238 appendix B
        self.assertEqual(totp.hotp(totp._key(key), 1111111109 // 30, 8), "07081804")
        self.assertEqual(totp.hotp(totp._key(key), 0), "755224")  # RFC 4226 appendix D
        self.assertEqual(totp.hotp(totp._key(key), 9), "520489")

    def test_setup_enable_shows_codes_and_secret_is_not_stored_plain(self):
        from .models import Account
        secret, codes = self._enable_2fa()
        self.assertEqual(len(codes), 8)
        acc = Account.objects.get()
        self.assertTrue(acc.totp_enabled)
        self.assertNotIn(secret, acc.totp_secret)
        self.assertNotIn(codes[0], acc.recovery_json)
        self.assertTrue(self.client.get("/v1/auth/me").json()["totp_enabled"])

    def test_wrong_code_does_not_enable(self):
        self._register()
        post_json(self.client, "/v1/auth/2fa/setup", {})
        self.assertEqual(post_json(self.client, "/v1/auth/2fa/enable", {"code": "000000"}).status_code, 400)
        self.assertFalse(self.client.get("/v1/auth/me").json()["totp_enabled"])

    def test_login_needs_second_step_then_works(self):
        from . import totp
        secret, codes = self._enable_2fa()
        post_json(self.client, "/v1/auth/logout", {})
        r = post_json(self.client, "/v1/auth/login", {"email": "ria@example.com", "password": self.PW})
        self.assertEqual(r.json(), {"needs_2fa": True})
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)  # not signed in yet
        bad = post_json(self.client, "/v1/auth/2fa/verify", {"code": "123456"})
        self.assertEqual(bad.status_code, 401)
        # the code used while enabling cannot be replayed, so use the next step
        import time as _t
        nxt = totp.code_at(secret, _t.time() + 30)
        ok = post_json(self.client, "/v1/auth/2fa/verify", {"code": nxt})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 200)

    def test_code_cannot_be_reused(self):
        from . import totp
        import time as _t
        secret, _ = self._enable_2fa()
        nxt = totp.code_at(secret, _t.time() + 30)
        for expect in (200, 401):
            post_json(self.client, "/v1/auth/logout", {})
            post_json(self.client, "/v1/auth/login", {"email": "ria@example.com", "password": self.PW})
            self.assertEqual(post_json(self.client, "/v1/auth/2fa/verify", {"code": nxt}).status_code, expect)

    def test_recovery_code_works_once(self):
        _, codes = self._enable_2fa()
        for expect in (200, 401):
            post_json(self.client, "/v1/auth/logout", {})
            post_json(self.client, "/v1/auth/login", {"email": "ria@example.com", "password": self.PW})
            self.assertEqual(post_json(self.client, "/v1/auth/2fa/verify", {"code": codes[0]}).status_code, expect)

    def test_second_step_attempts_are_limited(self):
        self._enable_2fa()
        post_json(self.client, "/v1/auth/logout", {})
        post_json(self.client, "/v1/auth/login", {"email": "ria@example.com", "password": self.PW})
        codes = [post_json(self.client, "/v1/auth/2fa/verify", {"code": "111111"}).status_code for _ in range(6)]
        self.assertEqual(codes[:5], [401] * 5)
        self.assertEqual(codes[5], 429)

    def test_verify_without_first_step_is_refused(self):
        self.assertEqual(post_json(Client(), "/v1/auth/2fa/verify", {"code": "123456"}).status_code, 400)

    def test_magic_link_also_needs_second_step(self):
        self._enable_2fa()
        post_json(self.client, "/v1/auth/logout", {})
        other = Client()
        post_json(other, "/v1/auth/magic/send", {"email": "ria@example.com"})
        r = post_json(other, "/v1/auth/magic", {"token": self._token("magic")})
        self.assertEqual(r.json(), {"needs_2fa": True})
        self.assertEqual(other.get("/v1/auth/me").status_code, 401)

    def test_disable_needs_a_valid_code(self):
        from . import totp
        import time as _t
        secret, _ = self._enable_2fa()
        self.assertEqual(post_json(self.client, "/v1/auth/2fa/disable", {"code": "000000"}).status_code, 400)
        r = post_json(self.client, "/v1/auth/2fa/disable", {"code": totp.code_at(secret, _t.time() + 30)})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self.client.get("/v1/auth/me").json()["totp_enabled"])


def _cbor(v):
    """Tiny CBOR writer, only for building test passkey data."""
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        if n < 256:
            return bytes([major << 5 | 24, n])
        return bytes([major << 5 | 25]) + n.to_bytes(2, "big")
    if isinstance(v, int):
        return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, bytes):
        return head(2, len(v)) + v
    if isinstance(v, str):
        return head(3, len(v.encode())) + v.encode()
    if isinstance(v, dict):
        return head(5, len(v)) + b"".join(_cbor(k) + _cbor(x) for k, x in v.items())
    raise TypeError(v)


class SoftPasskey:
    """A pretend phone: makes keys and signs like a real authenticator would."""

    def __init__(self, rp_id="testserver", origin="http://testserver"):
        import secrets
        from . import webauthn
        self.w, self.rp_id, self.origin = webauthn, rp_id, origin
        self.d = 1 + secrets.randbelow(webauthn.N - 1)
        self.q = webauthn.mul(self.d, webauthn.G)
        self.cid = secrets.token_bytes(32)
        self.counter = 0

    def _sign(self, message):
        import hashlib, secrets
        w = self.w
        e = int.from_bytes(hashlib.sha256(message).digest(), "big")
        while True:
            k = 1 + secrets.randbelow(w.N - 1)
            r = w.mul(k, w.G)[0] % w.N
            s = pow(k, -1, w.N) * (e + r * self.d) % w.N
            if r and s:
                break
        def der(i):
            b = i.to_bytes((i.bit_length() + 7) // 8, "big")
            return b"\x02" + bytes([len(b) + (b[0] >> 7)]) + (b"\x00" if b[0] >> 7 else b"") + b
        body = der(r) + der(s)
        return b"\x30" + bytes([len(body)]) + body

    def _client(self, kind, challenge, origin=None):
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin or self.origin}).encode()

    def create(self, challenge, flags=0x45, rp_id=None, origin=None):
        import hashlib
        from .passkey_views import b64e
        cose = _cbor({1: 2, 3: -7, -1: 1, -2: self.q[0].to_bytes(32, "big"), -3: self.q[1].to_bytes(32, "big")})
        auth = (hashlib.sha256((rp_id or self.rp_id).encode()).digest() + bytes([flags]) + self.counter.to_bytes(4, "big")
                + bytes(16) + len(self.cid).to_bytes(2, "big") + self.cid + cose)
        return {"id": b64e(self.cid), "response": {
            "clientDataJSON": b64e(self._client("webauthn.create", challenge, origin)),
            "attestationObject": b64e(_cbor({"fmt": "none", "attStmt": {}, "authData": auth}))}}

    def get(self, challenge, flags=0x05, counter=None, rp_id=None, origin=None, handle=None):
        import hashlib
        from .passkey_views import b64e
        self.counter = self.counter + 1 if counter is None else counter
        client = self._client("webauthn.get", challenge, origin)
        auth = hashlib.sha256((rp_id or self.rp_id).encode()).digest() + bytes([flags]) + self.counter.to_bytes(4, "big")
        sig = self._sign(auth + hashlib.sha256(client).digest())
        resp = {"clientDataJSON": b64e(client), "authenticatorData": b64e(auth), "signature": b64e(sig)}
        if handle:
            resp["userHandle"] = b64e(handle)
        return {"id": b64e(self.cid), "response": resp}


class WebAuthnUnitTests(SimpleTestCase):
    def test_cbor_rfc8949_examples(self):
        from .webauthn import cbor_decode
        self.assertEqual(cbor_decode(bytes.fromhex("1a000f4240")), 1000000)
        self.assertEqual(cbor_decode(bytes.fromhex("20")), -1)
        self.assertEqual(cbor_decode(bytes.fromhex("3903e7")), -1000)
        self.assertEqual(cbor_decode(bytes.fromhex("6449455446")), "IETF")
        self.assertEqual(cbor_decode(bytes.fromhex("83010203")), [1, 2, 3])
        self.assertEqual(cbor_decode(bytes.fromhex("a201020304")), {1: 2, 3: 4})
        self.assertEqual(cbor_decode(bytes.fromhex("4401020304")), b"\x01\x02\x03\x04")

    def test_cbor_rejects_garbage(self):
        from .webauthn import WebAuthnError, cbor_decode
        for bad in ("", "1a0000", "5f", "6449", "8301", "01ff", "a1"):
            with self.assertRaises(WebAuthnError):
                cbor_decode(bytes.fromhex(bad))
        with self.assertRaises(WebAuthnError):
            cbor_decode(b"\x81" * 50 + b"\x00")  # nested too deep

    def test_p256_rfc6979_vector(self):
        from . import webauthn as w
        q = (0x60FED4BA255A9D31C961EB74C6356D68C049B8923B61FA6CE669622E60F29FB6,
             0x7903FE1008B8BC99A41AE9E95628BC64F2F1B20C2D7E9F5177A3C294D4462299)
        r = 0xEFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716
        s = 0xF7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8
        def der(i):
            b = i.to_bytes(32, "big")
            return b"\x02" + bytes([33 if b[0] >> 7 else 32]) + (b"\x00" if b[0] >> 7 else b"") + b
        body = der(r) + der(s)
        sig = b"\x30" + bytes([len(body)]) + body
        self.assertTrue(w.on_curve(q))
        self.assertTrue(w.ecdsa_verify(q, b"sample", sig))
        self.assertFalse(w.ecdsa_verify(q, b"sample!", sig))
        self.assertFalse(w.ecdsa_verify(q, b"sample", sig[:-1] + bytes([sig[-1] ^ 1])))

    def test_agrees_with_a_real_crypto_library(self):
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import ec
        except ImportError:
            self.skipTest("cryptography not installed (only used to cross-check)")
        from . import webauthn as w
        for i in range(5):
            key = ec.generate_private_key(ec.SECP256R1())
            nums = key.public_key().public_numbers()
            msg = b"message %d" % i
            sig = key.sign(msg, ec.ECDSA(hashes.SHA256()))
            self.assertTrue(w.ecdsa_verify((nums.x, nums.y), msg, sig))
            self.assertFalse(w.ecdsa_verify((nums.x, nums.y), msg + b"x", sig))

    def test_signature_edge_cases_are_refused(self):
        from . import webauthn as w
        q = w.G
        for bad in (b"", b"\x30\x00", b"\x30\x06\x02\x01\x00\x02\x01\x01", b"\x30\x06\x02\x01\x01\x02\x01\x00", bytes(70)):
            self.assertFalse(w.ecdsa_verify(q, b"m", bad))
        self.assertFalse(w.ecdsa_verify((1, 2), b"m", b"\x30\x06\x02\x01\x01\x02\x01\x01"))  # point not on curve


class PasskeyApiTests(TestCase):
    PW = "Strong-pass-77x"

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client()
        post_json(self.client, "/v1/auth/register", {"email": "ria@example.com", "password": self.PW, "accept_terms": True})
        self.key = SoftPasskey()

    def _add(self, key=None, **kw):
        key = key or self.key
        ch = post_json(self.client, "/v1/auth/passkey/register/options", {}).json()["challenge"]
        return post_json(self.client, "/v1/auth/passkey/register", {**key.create(ch, **kw), "name": "My phone"})

    def _login(self, client, key=None, **kw):
        key = key or self.key
        ch = post_json(client, "/v1/auth/passkey/login/options", {}).json()["challenge"]
        return post_json(client, "/v1/auth/passkey/login", key.get(ch, **kw))

    def test_options_shape(self):
        o = post_json(self.client, "/v1/auth/passkey/register/options", {}).json()
        self.assertEqual(o["rp"]["id"], "testserver")
        self.assertEqual(o["pubKeyCredParams"], [{"type": "public-key", "alg": -7}])
        self.assertEqual(o["authenticatorSelection"]["userVerification"], "required")
        self.assertNotIn("ria@example.com", o["user"]["id"])

    def test_register_list_login_and_delete(self):
        r = self._add()
        self.assertEqual(r.status_code, 201)
        listing = self.client.get("/v1/auth/passkeys").json()["passkeys"]
        self.assertEqual([p["name"] for p in listing], ["My phone"])
        other = Client()
        self.assertEqual(other.get("/v1/auth/me").status_code, 401)
        ok = self._login(other)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(other.get("/v1/auth/me").json()["email"], "ria@example.com")
        self.assertEqual(self.client.delete("/v1/auth/passkeys/%s" % r.json()["id"]).status_code, 200)
        self.assertEqual(self._login(Client()).status_code, 401)

    def test_registering_needs_sign_in(self):
        self.assertEqual(post_json(Client(), "/v1/auth/passkey/register/options", {}).status_code, 401)

    def test_registration_checks(self):
        cases = ({"flags": 0x41}, {"flags": 0x05}, {"rp_id": "evil.example"}, {"origin": "http://evil.example"})
        for kw in cases:
            self.assertEqual(self._add(SoftPasskey(), **kw).status_code, 400, kw)
        self.assertEqual(self.client.get("/v1/auth/passkeys").json()["passkeys"], [])

    def test_registration_replay_and_wrong_challenge(self):
        ch = post_json(self.client, "/v1/auth/passkey/register/options", {}).json()["challenge"]
        body = self.key.create(ch)
        self.assertEqual(post_json(self.client, "/v1/auth/passkey/register", body).status_code, 201)
        self.assertEqual(post_json(self.client, "/v1/auth/passkey/register", body).status_code, 400)  # challenge is used up
        post_json(self.client, "/v1/auth/passkey/register/options", {})
        self.assertEqual(post_json(self.client, "/v1/auth/passkey/register", SoftPasskey().create("AAAA")).status_code, 400)

    def test_same_credential_cannot_be_added_twice(self):
        self._add()
        self.assertEqual(self._add().status_code, 400)

    def test_login_rejects_bad_answers(self):
        self._add()
        stranger = SoftPasskey()
        stranger.cid = self.key.cid  # same credential id, different private key
        checks = [(stranger, {}), (self.key, {"flags": 0x01}), (self.key, {"rp_id": "evil.example"}),
                  (self.key, {"origin": "http://evil.example"}), (self.key, {"handle": b"someone else"})]
        for key, kw in checks:
            c = Client()
            self.assertEqual(self._login(c, key, **kw).status_code, 401, kw)
            self.assertEqual(c.get("/v1/auth/me").status_code, 401)

    def test_login_challenge_is_one_time_and_not_interchangeable(self):
        self._add()
        c = Client()
        ch = post_json(c, "/v1/auth/passkey/login/options", {}).json()["challenge"]
        body = self.key.get(ch)
        self.assertEqual(post_json(c, "/v1/auth/passkey/login", body).status_code, 200)
        self.assertEqual(post_json(Client(), "/v1/auth/passkey/login", body).status_code, 401)  # other browser, no challenge
        c2 = Client()
        post_json(c2, "/v1/auth/passkey/login/options", {})
        self.assertEqual(post_json(c2, "/v1/auth/passkey/login", self.key.get(ch)).status_code, 401)  # stale challenge

    def test_counter_going_backwards_is_refused(self):
        self._add()
        self.assertEqual(self._login(Client(), counter=5).status_code, 200)
        self.assertEqual(self._login(Client(), counter=5).status_code, 401)
        self.assertEqual(self._login(Client(), counter=3).status_code, 401)
        self.assertEqual(self._login(Client(), counter=6).status_code, 200)

    def test_zero_counter_devices_still_work(self):
        self._add()
        for _ in range(2):
            self.assertEqual(self._login(Client(), counter=0).status_code, 200)

    def test_passkey_skips_second_step_even_with_2fa_on(self):
        from .models import Account
        Account.objects.update_or_create(user=get_user_model().objects.get(), defaults={"totp_enabled": True, "totp_secret": "x"})
        self._add()
        c = Client()
        self.assertEqual(self._login(c).status_code, 200)
        self.assertEqual(c.get("/v1/auth/me").status_code, 200)

    def test_other_users_cannot_delete_my_passkey(self):
        r = self._add()
        mallory = Client()
        post_json(mallory, "/v1/auth/register", {"email": "mal@example.com", "password": self.PW, "accept_terms": True})
        self.assertEqual(mallory.delete("/v1/auth/passkeys/%s" % r.json()["id"]).status_code, 404)
        self.assertEqual(len(self.client.get("/v1/auth/passkeys").json()["passkeys"]), 1)

    def test_limit_of_ten(self):
        for _ in range(10):
            self.assertEqual(self._add(SoftPasskey()).status_code, 201)
        self.assertEqual(post_json(self.client, "/v1/auth/passkey/register/options", {}).status_code, 400)


class QrTests(SimpleTestCase):
    def _decode(self, rows):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("OpenCV not installed (only used to cross-check the QR encoder)")
        scale, quiet, n = 8, 4, len(rows)
        img = np.full(((n + 2 * quiet) * scale,) * 2, 255, np.uint8)
        for r, row in enumerate(rows):
            for c, ch in enumerate(row):
                if ch == "1":
                    img[(r + quiet) * scale:(r + quiet + 1) * scale, (c + quiet) * scale:(c + quiet + 1) * scale] = 0
        return cv2.QRCodeDetector().detectAndDecode(img)[0]

    def test_shape(self):
        from . import qr
        rows = qr.encode("hello")
        self.assertEqual(len(rows), 21)
        self.assertTrue(all(len(r) == 21 and set(r) <= {"0", "1"} for r in rows))

    def test_decodes_back_for_many_lengths(self):
        from . import qr
        for n in (1, 17, 18, 60, 107, 200, 271, 400, 520):
            text = ("otpauth://totp/x?" + "aB3dE5fG" * 70)[:n]
            self.assertEqual(self._decode(qr.encode(text)), text, n)

    def test_real_setup_link_decodes(self):
        from . import qr, totp
        uri = totp.otpauth_uri(totp.new_secret(), "someone.with.a.long.name@example-university.ac.in")
        self.assertEqual(self._decode(qr.encode(uri)), uri)

    def test_too_long_is_refused(self):
        from . import qr
        with self.assertRaises(ValueError):
            qr.encode("x" * 600)


class AccountHygieneTests(TestCase):
    PW = "Strong-pass-77x"
    NEW = "Another-strong-pass-91"

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client()
        r = post_json(self.client, "/v1/auth/register", {"email": "ria@example.com", "password": self.PW, "name": "Ria", "accept_terms": True})
        self.assertEqual(r.status_code, 201)
        from django.core import mail
        mail.outbox.clear()

    # ----- change password -----
    def test_change_password_keeps_this_session_and_signs_out_others(self):
        other = Client()
        post_json(other, "/v1/auth/login", {"email": "ria@example.com", "password": self.PW})
        self.assertEqual(other.get("/v1/auth/me").status_code, 200)
        r = post_json(self.client, "/v1/auth/password", {"current": self.PW, "new": self.NEW})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 200)
        self.assertEqual(other.get("/v1/auth/me").status_code, 401)
        from django.core import mail
        self.assertIn("password was changed", mail.outbox[-1].subject)
        self.assertEqual(post_json(Client(), "/v1/auth/login", {"email": "ria@example.com", "password": self.NEW}).status_code, 200)
        self.assertEqual(post_json(Client(), "/v1/auth/login", {"email": "ria@example.com", "password": self.PW}).status_code, 401)

    def test_change_password_checks(self):
        self.assertEqual(post_json(self.client, "/v1/auth/password", {"current": "wrong-one-123", "new": self.NEW}).status_code, 400)
        self.assertEqual(post_json(self.client, "/v1/auth/password", {"new": self.NEW}).status_code, 400)  # current missing
        self.assertEqual(post_json(self.client, "/v1/auth/password", {"current": self.PW, "new": self.PW}).status_code, 400)
        weak = post_json(self.client, "/v1/auth/password", {"current": self.PW, "new": "12345678"})
        self.assertEqual((weak.status_code, weak.json()["error"]), (400, "weak password"))
        self.assertEqual(post_json(Client(), "/v1/auth/password", {"current": self.PW, "new": self.NEW}).status_code, 401)

    def test_wrong_current_password_is_limited(self):
        codes = [post_json(self.client, "/v1/auth/password", {"current": "wrong-one-123", "new": self.NEW}).status_code for _ in range(6)]
        self.assertEqual(codes, [400] * 5 + [429])

    def test_social_only_account_can_set_a_password(self):
        user = get_user_model().objects.get()
        user.set_unusable_password(); user.save()
        c = Client(); c.force_login(user)
        self.assertFalse(c.get("/v1/auth/me").json()["has_password"])
        r = post_json(c, "/v1/auth/password", {"new": self.NEW})
        self.assertEqual((r.status_code, r.json()["status"]), (200, "password set"))
        self.assertTrue(c.get("/v1/auth/me").json()["has_password"])

    # ----- export -----
    def _make_data(self):
        from .models import Profile, ProfilePhoto
        pid = post_json(self.client, "/v1/profiles", {"resume_text": RESUME}).json()["id"]
        ProfilePhoto.objects.create(profile=Profile.objects.get(id=pid), content_type="image/png", data=b"\x89PNG-fake")
        return pid

    def test_export_has_my_data_and_no_secrets(self):
        self._make_data()
        post_json(self.client, "/v1/auth/2fa/setup", {})
        r = self.client.get("/v1/me/export")
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        text = r.content.decode()
        data = json.loads(text)
        self.assertEqual(data["account"]["email"], "ria@example.com")
        self.assertEqual(len(data["cvs"]), 1)
        self.assertTrue(data["cvs"][0]["content"])
        self.assertEqual(data["cvs"][0]["photo"]["content_type"], "image/png")
        user = get_user_model().objects.get()
        from .models import Account
        for secret in (user.password, Account.objects.get().totp_secret, "pbkdf2"):
            self.assertNotIn(secret, text)

    def test_export_needs_sign_in_and_is_limited(self):
        self.assertEqual(Client().get("/v1/me/export").status_code, 401)
        codes = [self.client.get("/v1/me/export").status_code for _ in range(6)]
        self.assertEqual(codes, [200] * 5 + [429])

    def test_export_only_contains_my_rows(self):
        self._make_data()
        other = Client()
        post_json(other, "/v1/auth/register", {"email": "sam@example.com", "password": self.PW, "accept_terms": True})
        post_json(other, "/v1/profiles", {"resume_text": RESUME})
        mine = self.client.get("/v1/me/export").json()
        self.assertEqual(len(mine["cvs"]), 1)

    # ----- delete -----
    def test_delete_needs_the_right_confirmation(self):
        self._make_data()
        bad = ({"confirm_email": "someone@else.com", "password": self.PW}, {"confirm_email": "ria@example.com"},
               {"confirm_email": "ria@example.com", "password": "wrong-one-123"})
        for body in bad:
            self.assertEqual(post_json(self.client, "/v1/auth/delete", body).status_code, 400, body)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_delete_removes_everything_and_signs_out(self):
        from .models import Account, EmailToken, Job, Passkey, Profile, ProfilePhoto, ProfileVersion
        self._make_data()
        r = post_json(self.client, "/v1/auth/delete", {"confirm_email": " RIA@example.com ", "password": self.PW})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)
        for model in (get_user_model(), Profile, ProfilePhoto, ProfileVersion, Job, Account, EmailToken, Passkey):
            self.assertEqual(model.objects.count(), 0, model.__name__)
        from django.core import mail
        self.assertEqual(mail.outbox[-1].to, ["ria@example.com"])
        self.assertEqual(post_json(Client(), "/v1/auth/login", {"email": "ria@example.com", "password": self.PW}).status_code, 401)

    def test_delete_does_not_touch_other_users(self):
        other = Client()
        post_json(other, "/v1/auth/register", {"email": "sam@example.com", "password": self.PW, "accept_terms": True})
        post_json(other, "/v1/profiles", {"resume_text": RESUME})
        post_json(self.client, "/v1/auth/delete", {"confirm_email": "ria@example.com", "password": self.PW})
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(len(other.get("/v1/profiles").json()), 1)

    def test_delete_asks_for_2fa_code_when_on(self):
        import time as _t
        from . import totp
        secret = post_json(self.client, "/v1/auth/2fa/setup", {}).json()["secret"]
        post_json(self.client, "/v1/auth/2fa/enable", {"code": totp.code_at(secret)})
        body = {"confirm_email": "ria@example.com", "password": self.PW}
        self.assertEqual(post_json(self.client, "/v1/auth/delete", body).status_code, 400)
        body["code"] = totp.code_at(secret, _t.time() + 30)
        self.assertEqual(post_json(self.client, "/v1/auth/delete", body).status_code, 200)

    def test_delete_social_only_account_needs_only_the_typed_email(self):
        user = get_user_model().objects.get()
        user.set_unusable_password(); user.save()
        c = Client(); c.force_login(user)
        self.assertEqual(post_json(c, "/v1/auth/delete", {"confirm_email": "ria@example.com"}).status_code, 200)

    def test_wrong_delete_attempts_are_limited(self):
        codes = [post_json(self.client, "/v1/auth/delete", {"confirm_email": "no@no.com", "password": self.PW}).status_code for _ in range(6)]
        self.assertEqual(codes, [400] * 5 + [429])

    def test_setup_returns_a_qr_that_matches_the_link(self):
        r = post_json(self.client, "/v1/auth/2fa/setup", {}).json()
        self.assertTrue(r["uri"].startswith("otpauth://totp/"))
        self.assertEqual(len(r["qr"]), len(r["qr"][0]))
        self.assertTrue(17 + 4 <= len(r["qr"]) <= 77)


class ManyUsersTests(TestCase):
    PW = "Strong-pass-77x"

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _req(self, **meta):
        from django.test import RequestFactory
        return RequestFactory().get("/", **meta)

    def test_client_ip_ignores_forwarded_header_by_default(self):
        from .auth_views import _client_ip
        r = self._req(REMOTE_ADDR="10.0.0.9", HTTP_X_FORWARDED_FOR="1.2.3.4")
        self.assertEqual(_client_ip(r), "10.0.0.9")

    @override_settings(TRUSTED_PROXIES=1)
    def test_client_ip_behind_one_load_balancer(self):
        from .auth_views import _client_ip
        # a visitor tries to fake an address: only the entry added by our own proxy counts
        r = self._req(REMOTE_ADDR="10.0.0.9", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.7")
        self.assertEqual(_client_ip(r), "203.0.113.7")

    @override_settings(TRUSTED_PROXIES=2)
    def test_client_ip_behind_two_proxies_and_short_header(self):
        from .auth_views import _client_ip
        self.assertEqual(_client_ip(self._req(REMOTE_ADDR="10.0.0.9", HTTP_X_FORWARDED_FOR="9.9.9.9, 203.0.113.7, 10.1.1.1")), "203.0.113.7")
        self.assertEqual(_client_ip(self._req(REMOTE_ADDR="10.0.0.9", HTTP_X_FORWARDED_FOR="203.0.113.7")), "10.0.0.9")  # header too short: do not trust it

    @override_settings(IP_LIMIT_MULTIPLIER=5)
    def test_many_people_on_one_address_can_sign_up(self):
        codes = []
        for i in range(12):  # a classroom behind one Wi-Fi address
            c = Client()
            codes.append(post_json(c, "/v1/auth/register", {"email": "kid%d@example.com" % i, "password": self.PW, "accept_terms": True}).status_code)
        self.assertEqual(codes, [201] * 12)

    @override_settings(IP_LIMIT_MULTIPLIER=5)
    def test_sign_up_spam_from_one_address_is_still_stopped(self):
        codes = [post_json(Client(), "/v1/auth/register", {"email": "bot%d@example.com" % i, "password": self.PW, "accept_terms": True}).status_code for i in range(27)]
        self.assertEqual(codes[:25], [201] * 25)
        self.assertEqual(codes[25:], [429, 429])

    @override_settings(IP_LIMIT_MULTIPLIER=5)
    def test_one_persons_wrong_passwords_do_not_lock_the_whole_address(self):
        post_json(Client(), "/v1/auth/register", {"email": "a@example.com", "password": self.PW, "accept_terms": True})
        post_json(Client(), "/v1/auth/register", {"email": "b@example.com", "password": self.PW, "accept_terms": True})
        for _ in range(5):
            post_json(Client(), "/v1/auth/login", {"email": "a@example.com", "password": "wrong-pass-123"})
        self.assertEqual(post_json(Client(), "/v1/auth/login", {"email": "a@example.com", "password": self.PW}).status_code, 429)  # account a is locked
        self.assertEqual(post_json(Client(), "/v1/auth/login", {"email": "b@example.com", "password": self.PW}).status_code, 200)  # neighbour b is fine

    def test_ai_busy_answers_503_not_a_pile_up(self):
        from . import ai_views
        c = Client()
        post_json(c, "/v1/auth/register", {"email": "ai@example.com", "password": self.PW, "accept_terms": True})
        from . import security
        security.mark_verified(get_user_model().objects.get())
        pid = post_json(c, "/v1/profiles", {"resume_text": RESUME}).json()["id"]
        taken = []
        while ai_views._AI_SLOTS.acquire(blocking=False):
            taken.append(1)
        try:
            with mock.patch.object(ai_views, "build_gateway", return_value=object()):
                r = post_json(c, "/v1/profiles/%s/tailor" % pid, {"job_text": "Python developer"})
            self.assertEqual((r.status_code, r["Retry-After"], r.json()["code"]), (503, "30", "busy"))
        finally:
            for _ in taken:
                ai_views._AI_SLOTS.release()

    def test_sqlite_url_gets_safe_concurrency_options(self):
        from config.dburl import parse_database_url
        opts = parse_database_url("sqlite:///x.db")["OPTIONS"]
        self.assertEqual(opts["timeout"], 20)
        self.assertEqual(opts["transaction_mode"], "IMMEDIATE")
        self.assertIn("journal_mode=WAL", opts["init_command"])
        self.assertNotIn("OPTIONS", parse_database_url("sqlite://:memory:"))


class BuildFromScratchApiTests(TestCase):
    PW = "Strong-pass-77x"
    ANSWERS = {
        "contact": {"name": "Aarti Sharma", "email": "aarti@example.com", "phone": "+91 98200 11122", "location": "Thane", "links": "linkedin.com/in/aarti"},
        "role": "Python Developer",
        "education": [{"degree": "MCA", "school": "Mumbai University", "years": "2024-2026", "score": "CGPA 8.2"}],
        "skills": [{"group": "Languages", "items": "Python, JavaScript"}],
        "projects": [{"title": "ResumeWise", "tech": "Django", "points": ["Built a resume parser", "Wrote 200 tests"]}],
        "experience": [],
        "certifications": ["Python for Everybody"],
    }

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client()
        r = post_json(self.client, "/v1/auth/register", {"email": "sneha@example.com", "password": self.PW, "name": "Sneha", "accept_terms": True})
        self.assertEqual(r.status_code, 201)

    def test_build_creates_a_cv_that_every_other_feature_can_use(self):
        r = post_json(self.client, "/v1/profiles/build", self.ANSWERS)
        self.assertEqual(r.status_code, 201, r.content)
        pid = r.json()["id"]
        got = self.client.get("/v1/profiles/%s" % pid).json()["parsed"]
        texts = [i["text"] for s in got["sections"] for i in s["items"]]
        self.assertIn("MCA | Mumbai University | 2024-2026 | CGPA 8.2", texts)
        self.assertIn("Wrote 200 tests", texts)
        self.assertEqual(got["contact"]["email"], "aarti@example.com")
        self.assertEqual(self.client.get("/v1/profiles/%s/render?template=classic" % pid).status_code, 200)
        self.assertEqual(self.client.get("/v1/profiles/%s/ats?template=classic" % pid).status_code, 200)
        self.assertEqual(self.client.get("/v1/profiles/%s/export?format=docx" % pid).status_code, 200)
        add = post_json(self.client, "/v1/profiles/%s/items" % pid, {"section": "skills", "text": "SQL"})
        self.assertEqual(add.status_code, 201)

    def test_nothing_is_invented(self):
        r = post_json(self.client, "/v1/profiles/build", {"contact": {"name": "Ravi Kumar"}, "skills": [{"items": "Excel"}]})
        self.assertEqual(r.status_code, 201)
        parsed = r.json()["parsed"]
        self.assertEqual([s["key"] for s in parsed["sections"]], ["skills"])
        self.assertEqual(parsed["sections"][0]["items"][0]["text"], "Excel")

    def test_bad_answers_are_refused(self):
        for bad in [{}, {"contact": {"name": ""}, "skills": [{"items": "x"}]}, {"contact": {"name": "A B"}},
                    {"contact": {"name": "A B", "email": "nope"}, "skills": [{"items": "x"}]},
                    {"contact": {"name": "A B"}, "projects": "text"}, {"contact": {"name": "A B"}, "education": [1]},
                    {"contact": {"name": "A B", "links": "javascript:alert(1)"}, "skills": [{"items": "x"}]},
                    {"contact": {"name": "A B"}, "projects": [{"points": ["no title"]}]}]:
            r = post_json(self.client, "/v1/profiles/build", bad)
            self.assertEqual(r.status_code, 400, bad)

    def test_limits(self):
        big = dict(self.ANSWERS, projects=[{"title": "P%d" % i} for i in range(9)])
        self.assertEqual(post_json(self.client, "/v1/profiles/build", big).status_code, 400)
        long = dict(self.ANSWERS, summary="x" * 500)
        self.assertEqual(post_json(self.client, "/v1/profiles/build", long).status_code, 400)

    def test_login_required_and_html_is_escaped(self):
        self.assertEqual(post_json(Client(), "/v1/profiles/build", self.ANSWERS).status_code, 401)
        evil = dict(self.ANSWERS, summary="<script>alert(1)</script>")
        pid = post_json(self.client, "/v1/profiles/build", evil).json()["id"]
        html = self.client.get("/v1/profiles/%s/render?template=classic" % pid).content.decode()
        self.assertNotIn("<script>alert(1)", html)


class JobTrackerApiTests(TestCase):
    PW = "Strong-pass-77x"
    JD = "Python developer. Must have experience with Django and REST APIs. Knowledge of Docker is required. You will write test cases."

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client()
        r = post_json(self.client, "/v1/auth/register", {"email": "jobs@example.com", "password": self.PW, "name": "Jobs", "accept_terms": True})
        self.assertEqual(r.status_code, 201)
        r = post_json(self.client, "/v1/profiles/build", {
            "contact": {"name": "Aarti Sharma", "email": "aarti@example.com"},
            "education": [{"degree": "MCA", "school": "Mumbai University"}],
            "skills": [{"items": "Python, Django, SQL"}],
            "projects": [{"title": "ResumeWise", "points": ["Wrote 254 test cases", "Built REST APIs in Django"]}]})
        self.pid = r.json()["id"]

    def add(self, **extra):
        body = {"title": "Python Developer", "company": "Acme", "job_text": self.JD, "profile_id": self.pid}
        body.update(extra)
        return post_json(self.client, "/v1/jobs", body)

    def patch(self, jid, body):
        return self.client.patch("/v1/jobs/%s" % jid, data=json.dumps(body), content_type="application/json")

    def test_save_score_list_update_delete(self):
        r = self.add(url="https://example.com/job/1")
        self.assertEqual(r.status_code, 201, r.content)
        job = r.json()
        self.assertGreater(job["score"], 0)
        self.assertEqual(job["status"], "saved")
        self.assertEqual(len(self.client.get("/v1/jobs").json()["jobs"]), 1)
        self.assertEqual(self.patch(job["id"], {"status": "applied", "notes": "Applied on portal"}).json()["status"], "applied")
        d = self.client.get("/v1/jobs/%s?profile_id=%s" % (job["id"], self.pid)).json()
        self.assertEqual(d["notes"], "Applied on portal")
        self.assertIn("Built REST APIs in Django", [c["line"] for c in d["match"]["covered"]])
        self.assertIn("Docker", [m["name"] for m in d["match"]["missing"]])
        self.assertEqual(self.client.delete("/v1/jobs/%s" % job["id"]).status_code, 200)
        self.assertEqual(self.client.get("/v1/jobs").json()["jobs"], [])

    def test_bad_input(self):
        for extra in ({"title": ""}, {"job_text": " "}, {"url": "javascript:alert(1)"}, {"url": "ftp://x.com/a"},
                      {"title": "t" * 201}, {"company": 5}):
            self.assertIn(self.add(**extra).status_code, (400, 413), extra)
        self.assertEqual(self.add(job_text="x" * 8001).status_code, 413)
        j = self.add().json()
        self.assertEqual(self.patch(j["id"], {"status": "maybe"}).status_code, 400)
        self.assertEqual(self.patch(j["id"], {"url": "not a link"}).status_code, 400)

    def test_other_people_cannot_see_or_change_my_jobs(self):
        j = self.add().json()
        other = Client()
        post_json(other, "/v1/auth/register", {"email": "other@example.com", "password": self.PW, "name": "O", "accept_terms": True})
        self.assertEqual(other.get("/v1/jobs").json()["jobs"], [])
        self.assertEqual(other.get("/v1/jobs/%s" % j["id"]).status_code, 404)
        self.assertEqual(other.delete("/v1/jobs/%s" % j["id"]).status_code, 404)
        self.assertEqual(post_json(other, "/v1/jobs/%s/cover-letter" % j["id"], {"profile_id": self.pid}).status_code, 404)
        mine = self.client.get("/v1/jobs").json()["jobs"]
        self.assertEqual(len(mine), 1)
        # my job, someone else's CV
        stolen = post_json(other, "/v1/jobs", {"title": "t", "job_text": self.JD, "profile_id": self.pid})
        self.assertEqual(stolen.status_code, 201)
        self.assertIsNone(stolen.json()["score"])
        self.assertEqual(Client().get("/v1/jobs").status_code, 401)

    def test_job_limit(self):
        from packs import job_views
        old = job_views.MAX_JOBS
        job_views.MAX_JOBS = 2
        try:
            self.assertEqual(self.add().status_code, 201)
            self.assertEqual(self.add().status_code, 201)
            self.assertEqual(self.add().status_code, 409)
        finally:
            job_views.MAX_JOBS = old

    def test_cover_letter_uses_only_cv_facts(self):
        j = self.add().json()
        r = post_json(self.client, "/v1/jobs/%s/cover-letter" % j["id"], {"profile_id": self.pid, "why": "I like your product.", "manager": "Ms Rao"})
        self.assertEqual(r.status_code, 200, r.content)
        text = r.json()["text"]
        self.assertTrue(text.startswith("Dear Ms Rao,"))
        self.assertIn("Python Developer position at Acme", text)
        self.assertIn("Built REST APIs in Django", text)
        self.assertIn("I like your product.", text)
        self.assertIn("Aarti Sharma", text)
        self.assertNotIn("Docker", text)  # the CV does not show it, so the letter never mentions it
        self.assertEqual(r.json()["left_out"], ["Docker"])
        self.assertEqual(post_json(self.client, "/v1/jobs/%s/cover-letter" % j["id"], {"profile_id": "nope"}).status_code, 400)

    def test_interview_questions_and_saved_answers(self):
        j = self.add().json()
        r = self.client.get("/v1/jobs/%s/interview?profile_id=%s" % (j["id"], self.pid))
        qs = r.json()["questions"]
        self.assertEqual(qs[0]["id"], "intro")
        gap = [q for q in qs if q["kind"] == "gap"]
        self.assertTrue(gap and "Docker" in gap[0]["question"] and "Never claim" in gap[0]["tip"])
        put = lambda body: self.client.put("/v1/jobs/%s/interview" % j["id"], data=json.dumps(body), content_type="application/json")  # noqa: E731
        ok = put({"profile_id": self.pid, "answers": {"intro": "I am Aarti."}})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["questions"][0]["answer"], "I am Aarti.")
        self.assertEqual(self.client.get("/v1/jobs/%s/interview?profile_id=%s" % (j["id"], self.pid)).json()["questions"][0]["answer"], "I am Aarti.")
        self.assertEqual(put({"profile_id": self.pid, "answers": {"nope": "x"}}).status_code, 400)
        self.assertEqual(put({"profile_id": self.pid, "answers": {"intro": "x" * 2001}}).status_code, 413)
        self.assertEqual(put({"profile_id": self.pid, "answers": {"intro": 5}}).status_code, 400)

    def test_jobs_are_in_my_data_and_purged_when_old(self):
        j = self.add().json()
        self.patch(j["id"], {"notes": "remember"})
        data = self.client.get("/v1/me/export").json()
        self.assertEqual(data["jobs"][0]["notes"], "remember")
        self.assertEqual(data["jobs"][0]["status"], "saved")
        from packs.models import Job
        from django.utils import timezone
        from datetime import timedelta
        Job.objects.update(expires_at=timezone.now() - timedelta(days=1))
        from django.core.management import call_command
        call_command("purge_expired", stdout=__import__("io").StringIO())
        self.assertEqual(Job.objects.count(), 0)


class AbuseProtectionTests(TestCase):
    PW = "Strong-pass-77x"

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def register(self, client, email, **extra):
        body = {"email": email, "password": self.PW, "name": "T", "accept_terms": True}
        body.update(extra)
        return post_json(client, "/v1/auth/register", body)

    def solved(self, client, wait=True):
        from packs import botcheck
        ch = client.get("/v1/auth/challenge").json()
        if wait:
            time.sleep(botcheck.MIN_AGE + 0.1)
        return {"bot_token": ch["token"], "bot_nonce": botcheck.solve(ch["token"], ch["bits"])}

    @override_settings(BOT_CHECK=True)
    def test_bot_check_passes_for_a_person_and_blocks_shortcuts(self):
        c = Client()
        self.assertEqual(self.register(c, "nobody@example.com").status_code, 400)                         # no token
        ok = self.solved(c)
        self.assertEqual(self.register(c, "p1@example.com", **ok).status_code, 201)                       # solved, waited
        self.assertEqual(self.register(Client(), "p2@example.com", **ok).status_code, 400)                 # same token again
        fast = self.solved(c, wait=False)
        self.assertEqual(self.register(Client(), "p3@example.com", **fast).status_code, 400)               # too fast
        good = self.solved(c)
        self.assertEqual(self.register(Client(), "p4@example.com", website="http://spam", **good).status_code, 400)  # hidden field
        good = self.solved(c)
        good["bot_nonce"] = int(good["bot_nonce"]) + 1                                                      # wrong work (almost surely)
        r = self.register(Client(), "p5@example.com", **good)
        self.assertIn(r.status_code, (400, 201))
        bad = {"bot_token": "garbage", "bot_nonce": 1}
        self.assertEqual(self.register(Client(), "p6@example.com", **bad).status_code, 400)

    @override_settings(BOT_CHECK=True)
    def test_forgot_and_magic_need_the_check_too(self):
        c = Client()
        for url in ("/v1/auth/forgot", "/v1/auth/magic/send"):
            self.assertEqual(post_json(c, url, {"email": "x@example.com"}).status_code, 400)
            self.assertEqual(post_json(c, url, dict({"email": "x@example.com"}, **self.solved(c))).status_code, 200)

    def test_check_is_off_in_tests_by_default(self):
        self.assertEqual(self.register(Client(), "plain@example.com").status_code, 201)

    @override_settings(SIGNUPS_PER_IP_PER_DAY=2, IP_LIMIT_MULTIPLIER=1)
    def test_daily_signup_cap_per_network(self):
        codes = [self.register(Client(), "d%d@example.com" % i).status_code for i in range(4)]
        self.assertEqual(codes, [201, 201, 429, 429])

    def test_error_is_recorded_without_personal_data(self):
        from packs.models import ErrorEvent
        user = get_user_model().objects.create_user("err@example.com", password=self.PW)
        c = Client(raise_request_exception=False)
        c.force_login(user)
        with mock.patch("core.job_match.analyse", side_effect=RuntimeError("boom")):
            r = post_json(c, "/v1/profiles/build", {"contact": {"name": "A B"}, "skills": [{"items": "x"}]})
            pid = r.json()["id"]
            j = post_json(c, "/v1/jobs", {"title": "t", "job_text": "x", "profile_id": pid})
        self.assertEqual(j.status_code, 500)
        e = ErrorEvent.objects.get()
        self.assertEqual((e.method, e.path, e.kind, e.user_id), ("POST", "/v1/jobs", "RuntimeError", user.pk))

    def test_admin_stats_only_for_staff(self):
        user = get_user_model().objects.create_user("plain@example.com", password=self.PW)
        c = Client()
        self.assertEqual(c.get("/v1/admin/stats").status_code, 401)
        c.force_login(user)
        self.assertEqual(c.get("/v1/admin/stats").status_code, 404)
        call_command("make_staff", "plain@example.com", stdout=__import__("io").StringIO())
        data = c.get("/v1/admin/stats").json()
        self.assertEqual(data["users"]["total"], 1)
        self.assertEqual(data["errors"]["count_24h"], 0)
        self.assertNotIn("plain@example.com", json.dumps(data))
        call_command("make_staff", "plain@example.com", "--remove", stdout=__import__("io").StringIO())
        self.assertEqual(c.get("/v1/admin/stats").status_code, 404)

    def test_make_staff_unknown_email(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("make_staff", "nobody@example.com")

    @override_settings(AI_DAILY_PER_USER=1)
    def test_daily_ai_limit_per_person(self):
        from core import gateway as gw
        from packs.models import Profile
        user = get_user_model().objects.create_user("ai@example.com", password=self.PW)
        from packs.models import Account
        from django.utils import timezone as tz
        Account.objects.create(user=user, email_verified_at=tz.now())
        c = Client()
        c.force_login(user)
        pid = post_json(c, "/v1/profiles", {"resume_text": TailorApiTests.TEXT}).json()["id"]
        fake = gw.FakeProvider([json.dumps(TailorApiTests.GOOD)] * 3)
        with mock.patch("packs.ai_views.build_gateway", lambda: gw.Gateway({"tailor": fake})):
            first = post_json(c, "/v1/profiles/%s/tailor" % pid, {"job_text": "Need Django"})
            second = post_json(c, "/v1/profiles/%s/tailor" % pid, {"job_text": "Need Django"})
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["code"], "daily_limit")

    @override_settings(AI_DAILY_BUDGET_PAISE=1)
    def test_daily_ai_budget_for_everyone(self):
        from core import gateway as gw
        from packs.models import Account, Run
        user = get_user_model().objects.create_user("ai2@example.com", password=self.PW)
        Account.objects.create(user=user, email_verified_at=timezone.now())
        c = Client()
        c.force_login(user)
        pid = post_json(c, "/v1/profiles", {"resume_text": TailorApiTests.TEXT}).json()["id"]
        job = Job.objects.create(user=user, title="x", raw_text="x")
        Run.objects.create(profile=Profile.objects.get(id=pid), job=job, status="ready", cost_paise=5)
        fake = gw.FakeProvider([json.dumps(TailorApiTests.GOOD)] * 3)
        with mock.patch("packs.ai_views.build_gateway", lambda: gw.Gateway({"tailor": fake})):
            r = post_json(c, "/v1/profiles/%s/tailor" % pid, {"job_text": "Need Django"})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["code"], "budget")


class WritingHelpApiTests(TestCase):
    PW = "Strong-pass-77x"

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client()
        post_json(self.client, "/v1/auth/register", {"email": "wh@example.com", "password": self.PW, "name": "W", "accept_terms": True})
        self.pid = post_json(self.client, "/v1/profiles/build", {
            "contact": {"name": "Aarti Sharma", "email": "aarti@example.com"},
            "skills": [{"items": "Python"}],
            "projects": [{"title": "ResumeWise", "points": ["Worked on testing of web modules", "Tested 12 modules and logged 40 defects"]}]}).json()["id"]

    def test_review_flags_weak_lines_and_leaves_good_ones(self):
        d = self.client.get("/v1/profiles/%s/review" % self.pid).json()
        flagged = {l["text"]: [t["code"] for t in l["tips"]] for l in d["lines"]}
        self.assertEqual(flagged["Worked on testing of web modules"], ["weak_start", "no_number"])
        self.assertNotIn("Tested 12 modules and logged 40 defects", flagged)
        self.assertNotIn("Python", flagged)
        self.assertEqual(d["flagged"], len(d["lines"]))
        weak = [t for l in d["lines"] for t in l["tips"] if t["code"] == "weak_start"][0]
        self.assertIn("Tested", weak["verbs"])

    def test_review_is_private(self):
        other = Client()
        post_json(other, "/v1/auth/register", {"email": "wh2@example.com", "password": self.PW, "name": "O", "accept_terms": True})
        self.assertEqual(other.get("/v1/profiles/%s/review" % self.pid).status_code, 404)
        self.assertEqual(Client().get("/v1/profiles/%s/review" % self.pid).status_code, 401)

    def test_live_line_check(self):
        r = post_json(self.client, "/v1/bullets/check", {"text": "I built a login page", "section": "projects"})
        self.assertEqual([t["code"] for t in r.json()["tips"]], ["first_person", "no_number"])
        self.assertEqual(post_json(self.client, "/v1/bullets/check", {"text": "x" * 1001}).status_code, 400)
        self.assertEqual(post_json(self.client, "/v1/bullets/check", {"text": 5}).status_code, 400)
        self.assertEqual(post_json(Client(), "/v1/bullets/check", {"text": "a"}).status_code, 401)

    def test_scanner_findings_say_how_to_fix(self):
        d = self.client.get("/v1/profiles/%s/ats?template=classic" % self.pid).json()
        self.assertTrue(d["findings"])
        for f in d["findings"]:
            self.assertTrue(f.get("fix"), f)


def _reminders(outbox):
    return [m for m in outbox if "follow up" in m.subject]


class FollowUpReminderTests(JobTrackerApiTests):
    """Step 10: follow-up day, due list and the daily reminder email."""

    def mark_applied(self, jid):
        return self.patch(jid, {"status": "applied"})

    def test_applied_sets_day_and_default_follow_up(self):
        from datetime import timedelta
        from django.utils import timezone
        jid = self.add().json()["id"]
        r = self.mark_applied(jid).json()
        today = timezone.localdate()
        self.assertEqual(r["applied_on"], today.isoformat())
        self.assertEqual(r["follow_up_on"], (today + timedelta(days=7)).isoformat())
        self.assertFalse(r["due"])
        self.assertEqual(r["days_since_applied"], 0)

    def test_changing_status_back_and_forth_keeps_first_applied_day(self):
        jid = self.add().json()["id"]
        first = self.mark_applied(jid).json()["applied_on"]
        self.patch(jid, {"status": "interview"})
        self.assertEqual(self.mark_applied(jid).json()["applied_on"], first)

    def test_due_list_and_snooze(self):
        from datetime import timedelta
        from django.utils import timezone
        from packs.models import Job
        jid = self.add().json()["id"]
        self.mark_applied(jid)
        self.assertEqual(self.client.get("/v1/jobs/due").json()["jobs"], [])
        Job.objects.filter(id=jid).update(follow_up_on=timezone.localdate() - timedelta(days=1))
        due = self.client.get("/v1/jobs/due").json()["jobs"]
        self.assertEqual([j["id"] for j in due], [jid])
        self.assertTrue(due[0]["due"])
        later = (timezone.localdate() + timedelta(days=3)).isoformat()
        self.assertEqual(self.patch(jid, {"follow_up_on": later}).json()["follow_up_on"], later)
        self.assertEqual(self.client.get("/v1/jobs/due").json()["jobs"], [])

    def test_moving_on_removes_from_due(self):
        from datetime import timedelta
        from django.utils import timezone
        from packs.models import Job
        jid = self.add().json()["id"]
        self.mark_applied(jid)
        Job.objects.filter(id=jid).update(follow_up_on=timezone.localdate() - timedelta(days=2))
        self.patch(jid, {"status": "interview"})
        self.assertEqual(self.client.get("/v1/jobs/due").json()["jobs"], [])

    def test_bad_follow_up_inputs(self):
        jid = self.add().json()["id"]
        for bad in ("tomorrow", "2020-01-01", "2099-01-01", 5, ["x"]):
            self.assertEqual(self.patch(jid, {"follow_up_on": bad}).status_code, 400, bad)
        self.assertEqual(self.patch(jid, {"remind_email": "yes"}).status_code, 400)
        self.assertEqual(self.patch(jid, {"follow_up_on": ""}).status_code, 200)

    def test_other_users_jobs_not_in_due(self):
        from datetime import timedelta
        from django.utils import timezone
        from packs.models import Job
        jid = self.add().json()["id"]
        self.mark_applied(jid)
        Job.objects.filter(id=jid).update(follow_up_on=timezone.localdate() - timedelta(days=1))
        other = Client()
        post_json(other, "/v1/auth/register", {"email": "other-due@example.com", "password": self.PW, "name": "O", "accept_terms": True})
        self.assertEqual(other.get("/v1/jobs/due").json()["jobs"], [])
        self.assertEqual(other.patch("/v1/jobs/%s" % jid, data=json.dumps({"follow_up_on": ""}), content_type="application/json").status_code, 404)

    def test_requires_login(self):
        self.assertEqual(Client().get("/v1/jobs/due").status_code, 401)

    def _make_due(self, **extra):
        from datetime import timedelta
        from django.utils import timezone
        from packs.models import Job
        jid = self.add().json()["id"]
        self.mark_applied(jid)
        Job.objects.filter(id=jid).update(follow_up_on=timezone.localdate() - timedelta(days=1), **extra)
        return jid

    def _confirm(self):
        from django.contrib.auth import get_user_model
        from packs import security
        security.mark_verified(get_user_model().objects.get(email="jobs@example.com"))

    def test_command_sends_one_email_once(self):
        from django.core import mail
        from django.core.management import call_command
        from packs.models import Job
        self.add(title="Second Job")
        jid = self._make_due()
        self._confirm()
        call_command("send_reminders", stdout=__import__("io").StringIO())
        self.assertEqual(len(_reminders(mail.outbox)), 1)
        body = _reminders(mail.outbox)[0].body
        self.assertIn("Python Developer - Acme", body)
        self.assertNotIn("Second Job", body)  # only applied jobs
        self.assertNotIn("Django", body)  # no job text or notes
        self.assertIsNotNone(Job.objects.get(id=jid).reminded_at)
        call_command("send_reminders", stdout=__import__("io").StringIO())
        self.assertEqual(len(_reminders(mail.outbox)), 1)  # not twice

    def test_new_follow_up_day_arms_again(self):
        from datetime import timedelta
        from django.core import mail
        from django.core.management import call_command
        from django.utils import timezone
        from packs.models import Job
        jid = self._make_due()
        self._confirm()
        call_command("send_reminders", stdout=__import__("io").StringIO())
        self.patch(jid, {"follow_up_on": (timezone.localdate() + timedelta(days=2)).isoformat()})
        Job.objects.filter(id=jid).update(follow_up_on=timezone.localdate() - timedelta(days=1))
        Job.objects.filter(id=jid).update(reminded_at=None)
        call_command("send_reminders", stdout=__import__("io").StringIO())
        self.assertEqual(len(_reminders(mail.outbox)), 2)

    def test_command_respects_opt_out_and_unconfirmed(self):
        from django.core import mail
        from django.core.management import call_command
        self._make_due()
        call_command("send_reminders", stdout=__import__("io").StringIO())
        self.assertEqual(len(_reminders(mail.outbox)), 0)  # email not confirmed
        self._confirm()
        from packs.models import Job
        Job.objects.update(remind_email=False)
        call_command("send_reminders", stdout=__import__("io").StringIO())
        self.assertEqual(len(_reminders(mail.outbox)), 0)  # switched off

    def test_dry_run_sends_nothing(self):
        from django.core import mail
        from django.core.management import call_command
        from packs.models import Job
        jid = self._make_due()
        self._confirm()
        call_command("send_reminders", "--dry-run", stdout=__import__("io").StringIO())
        self.assertEqual(len(_reminders(mail.outbox)), 0)
        self.assertIsNone(Job.objects.get(id=jid).reminded_at)

    def test_export_has_follow_up_fields(self):
        self.mark_applied(self.add().json()["id"])
        job = self.client.get("/v1/me/export").json()["jobs"][0]
        self.assertIsNotNone(job["applied_on"])
        self.assertIsNotNone(job["follow_up_on"])
        self.assertTrue(job["reminder_email_on"])


class FeedbackApiTests(TestCase):
    PW = "Strong-pass-77x"

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client()
        post_json(self.client, "/v1/auth/register", {"email": "fb@example.com", "password": self.PW, "name": "Fb", "accept_terms": True})

    def test_send_and_admin_sees_it(self):
        from django.contrib.auth import get_user_model
        r = post_json(self.client, "/v1/feedback", {"message": "The wizard is great", "kind": "idea", "page": "cv"})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.client.get("/v1/admin/stats").status_code, 404)
        get_user_model().objects.filter(email="fb@example.com").update(is_staff=True)
        fb = self.client.get("/v1/admin/stats").json()["feedback"]
        self.assertEqual(fb[0]["message"], "The wizard is great")
        self.assertEqual(fb[0]["email"], "fb@example.com")

    def test_bad_inputs(self):
        for body in ({"message": ""}, {"message": "hi"}, {"message": 5}, {"message": "enough words", "kind": "rant"}):
            self.assertEqual(post_json(self.client, "/v1/feedback", body).status_code, 400, body)
        self.assertEqual(post_json(self.client, "/v1/feedback", {"message": "x" * 2001}).status_code, 413)

    def test_daily_limit(self):
        for _ in range(10):
            self.assertEqual(post_json(self.client, "/v1/feedback", {"message": "some feedback here"}).status_code, 201)
        self.assertEqual(post_json(self.client, "/v1/feedback", {"message": "some feedback here"}).status_code, 429)

    def test_login_required_and_in_export_and_deleted_with_account(self):
        from packs.models import Feedback
        self.assertEqual(post_json(Client(), "/v1/feedback", {"message": "no account here"}).status_code, 401)
        post_json(self.client, "/v1/feedback", {"message": "keep this note"})
        self.assertEqual(self.client.get("/v1/me/export").json()["feedback_sent"][0]["message"], "keep this note")
        self.assertEqual(Feedback.objects.count(), 1)
        from django.contrib.auth import get_user_model
        get_user_model().objects.get(email="fb@example.com").delete()
        self.assertEqual(Feedback.objects.count(), 0)


class TrustPagesServedTests(TestCase):
    def test_scripts_are_served_with_strict_headers(self):
        for name in ("legal.js", "i18n.js", "app.js"):
            r = Client().get("/app/" + name)
            self.assertEqual(r.status_code, 200, name)
            self.assertIn("text/javascript", r["Content-Type"])
            self.assertIn("script-src 'self'", r["Content-Security-Policy"])
        page = Client().get("/app/index.html").content.decode()
        self.assertIn("/app/legal.js", page)

    def test_legal_text_is_marked_draft_and_covers_the_basics(self):
        text = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "legal.js"), encoding="utf-8").read()
        for needle in ("lawyer", "30 days", "Anthropic", "Delete my account", "Download my data", "[support email]"):
            self.assertIn(needle, text)


class DeployToolsTests(TestCase):
    def test_health_ok_and_down(self):
        from unittest import mock
        r = Client().get("/v1/health")
        self.assertEqual((r.status_code, r.json()), (200, {"status": "ok"}))
        with mock.patch("django.db.backends.utils.CursorWrapper.execute", side_effect=RuntimeError("db gone")):
            r = Client().get("/v1/health")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"status": "down"})  # no details leaked

    def test_alert_is_sent_once_per_window_and_only_when_configured(self):
        from django.core import mail
        from django.core.cache import cache
        from django.test import override_settings
        from packs import alerts
        cache.clear()
        with override_settings(ALERT_EMAIL=""):
            self.assertFalse(alerts.notify("ValueError", "/v1/x", "boom"))
        with override_settings(ALERT_EMAIL="owner@example.com, second@example.com"):
            self.assertTrue(alerts.notify("ValueError", "/v1/x", "boom"))
            self.assertFalse(alerts.notify("ValueError", "/v1/x", "boom again"))  # throttled
            self.assertTrue(alerts.notify("KeyError", "/v1/x", "other kind"))
        sent = [m for m in mail.outbox if "server error" in m.subject]
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0].to, ["owner@example.com", "second@example.com"])

    def test_alert_email_has_no_request_data(self):
        from django.core import mail
        from django.core.cache import cache
        from django.test import override_settings
        from packs import alerts
        cache.clear()
        with override_settings(ALERT_EMAIL="owner@example.com"):
            alerts.notify("ValueError", "/v1/profiles/<id>", "short")
        self.assertNotIn("password", mail.outbox[-1].body.lower())

    def test_backup_verify_and_prune(self):
        import sqlite3, tempfile, time
        from pathlib import Path
        from django.core.management.base import CommandError
        from packs.management.commands import backup
        with tempfile.TemporaryDirectory() as d:
            good = Path(d) / "resumewise-1.sqlite3"
            conn = sqlite3.connect(good)
            conn.execute("CREATE TABLE auth_user (id integer)")
            conn.execute("INSERT INTO auth_user VALUES (1)")
            conn.commit(); conn.close()
            self.assertIn("1 accounts", backup.verify(good))
            empty = Path(d) / "resumewise-2.sqlite3"
            empty.write_bytes(b"")
            with self.assertRaises(CommandError):
                backup.verify(empty)
            old = Path(d) / "resumewise-old.sqlite3"
            old.write_bytes(b"x")
            ancient = time.time() - 40 * 86400
            os.utime(old, (ancient, ancient))
            self.assertEqual(backup.prune(d, 14), 1)
            self.assertFalse(old.exists())
            self.assertTrue(good.exists())

    def test_backup_makes_a_readable_copy_of_a_sqlite_file(self):
        import sqlite3, tempfile
        from pathlib import Path
        from django.test import override_settings
        from packs.management.commands import backup
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "live.sqlite3"
            conn = sqlite3.connect(src)
            conn.execute("CREATE TABLE auth_user (id integer)")
            conn.execute("INSERT INTO auth_user VALUES (1)")
            conn.commit(); conn.close()
            dbs = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(src)}}
            with override_settings(DATABASES=dbs):
                out = backup.make_backup(Path(d) / "out")
            self.assertIn("1 accounts", backup.verify(out))
            self.assertEqual(oct(out.stat().st_mode & 0o777), "0o600")


# ---------------- step 15: payments ----------------
import hashlib as _hashlib
import hmac as _hmac
import threading as _threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _FakeRazorpay:
    """A tiny local stand-in for api.razorpay.com so the real request code runs without internet."""

    def __init__(self, status=200):
        self.requests, self.status, outer = [], status, self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
                if outer.status != 200:
                    out = {"error": {"description": "Authentication failed"}}
                else:
                    out = {"id": "plink_%d" % len(outer.requests), "short_url": "https://rzp.io/i/test%d" % len(outer.requests)}
                data = json.dumps(out).encode()
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_port
        _threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


KEY_ID, KEY_SECRET, HOOK_SECRET = "rzp_test_abc", "key-secret-123", "hook-secret-456"


def _sign(secret, message):
    return _hmac.new(secret.encode(), message if isinstance(message, bytes) else message.encode(), _hashlib.sha256).hexdigest()


class PaymentsApiTests(TestCase):
    PW = "Strong-pass-77x"

    def setUp(self):
        from django.core.cache import cache
        from django.test import override_settings
        cache.clear()
        self.fake = _FakeRazorpay()
        self.addCleanup(self.fake.close)
        cfg = override_settings(RAZORPAY_KEY_ID=KEY_ID, RAZORPAY_KEY_SECRET=KEY_SECRET, RAZORPAY_WEBHOOK_SECRET=HOOK_SECRET,
                                RAZORPAY_API=self.fake.url, SITE_URL="https://rw.example.com", FREE_AI_PER_DAY=1, FREE_MAX_JOBS=1)
        cfg.enable()
        self.addCleanup(cfg.disable)
        self.client = Client()
        r = post_json(self.client, "/v1/auth/register", {"email": "pay@example.com", "password": self.PW, "name": "Pay", "accept_terms": True})
        self.assertEqual(r.status_code, 201)
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.get(email="pay@example.com")
        from packs import security
        security.mark_verified(self.user)

    def buy(self, plan="pro_30"):
        r = post_json(self.client, "/v1/billing/checkout", {"plan": plan})
        self.assertEqual(r.status_code, 201, r.content)
        from packs.models import Payment
        return Payment.objects.order_by("-created_at").first()

    def back_params(self, payment, status="paid", pay_id="pay_111", secret=KEY_SECRET):
        sig = _sign(secret, "|".join([payment.link_id, payment.reference, status, pay_id]))
        return {"razorpay_payment_id": pay_id, "razorpay_payment_link_id": payment.link_id,
                "razorpay_payment_link_reference_id": payment.reference, "razorpay_payment_link_status": status, "razorpay_signature": sig}

    def hook(self, event, secret=HOOK_SECRET):
        raw = json.dumps(event).encode()
        return Client().post("/v1/billing/webhook", data=raw, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=_sign(secret, raw))

    def paid_event(self, payment, amount=None, pay_id="pay_222"):
        return {"event": "payment_link.paid", "payload": {
            "payment_link": {"entity": {"id": payment.link_id, "reference_id": payment.reference}},
            "payment": {"entity": {"id": pay_id, "amount": payment.amount_paise if amount is None else amount}}}}

    # --- status and limits ---
    def test_status_shows_free_plan_and_limits(self):
        d = self.client.get("/v1/billing").json()
        self.assertTrue(d["enabled"])
        self.assertEqual((d["plan"], d["pro_until"]), ("free", None))
        self.assertEqual(d["limits"], {"ai_per_day": 1, "max_jobs": 1})
        self.assertEqual([p["key"] for p in d["plans"]], ["pro_30", "pro_90"])

    def test_not_enabled_means_everyone_has_full_limits(self):
        from django.test import override_settings
        with override_settings(RAZORPAY_KEY_ID=""):
            d = self.client.get("/v1/billing").json()
            self.assertFalse(d["enabled"])
            self.assertEqual(d["limits"]["max_jobs"], 100)
            r = post_json(self.client, "/v1/billing/checkout", {"plan": "pro_30"})
            self.assertEqual(r.status_code, 503)

    def test_free_job_limit_then_pro_lifts_it(self):
        body = {"title": "Dev", "company": "A", "job_text": "Python developer with Django"}
        self.assertEqual(post_json(self.client, "/v1/jobs", body).status_code, 201)
        r = post_json(self.client, "/v1/jobs", body)
        self.assertEqual(r.status_code, 409)
        self.assertIn("Pro plan", r.json()["error"])
        from packs import billing
        billing.grant(self.buy().pk, "pay_1")
        self.assertEqual(post_json(self.client, "/v1/jobs", body).status_code, 201)

    # --- checkout ---
    def test_checkout_talks_to_razorpay_correctly(self):
        p = self.buy("pro_90")
        sent = self.fake.requests[0]
        self.assertEqual(sent["path"], "/v1/payment_links")
        import base64
        self.assertEqual(sent["auth"], "Basic " + base64.b64encode(("%s:%s" % (KEY_ID, KEY_SECRET)).encode()).decode())
        b = sent["body"]
        self.assertEqual((b["amount"], b["currency"], b["reference_id"]), (34900, "INR", p.reference))
        self.assertEqual(b["callback_url"], "https://rw.example.com/v1/billing/return")
        self.assertEqual(b["customer"]["email"], "pay@example.com")
        self.assertNotIn("password", json.dumps(b).lower())
        self.assertEqual((p.status, p.days, p.link_url), ("created", 90, "https://rzp.io/i/test1"))

    def test_checkout_needs_login_valid_plan_and_confirmed_email(self):
        self.assertEqual(post_json(Client(), "/v1/billing/checkout", {"plan": "pro_30"}).status_code, 401)
        self.assertEqual(post_json(self.client, "/v1/billing/checkout", {"plan": "gold"}).status_code, 400)
        c2 = Client()
        post_json(c2, "/v1/auth/register", {"email": "unconfirmed@example.com", "password": self.PW, "name": "U", "accept_terms": True})
        self.assertEqual(post_json(c2, "/v1/billing/checkout", {"plan": "pro_30"}).status_code, 403)

    def test_checkout_provider_error_leaves_nothing_behind(self):
        from packs.models import Payment
        self.fake.status = 401
        r = post_json(self.client, "/v1/billing/checkout", {"plan": "pro_30"})
        self.assertEqual(r.status_code, 502)
        self.assertIn("Authentication failed", r.json()["error"])
        self.assertEqual(Payment.objects.count(), 0)

    def test_checkout_rate_limit(self):
        for _ in range(5):
            self.buy()
        self.assertEqual(post_json(self.client, "/v1/billing/checkout", {"plan": "pro_30"}).status_code, 429)

    # --- the page Razorpay sends people back to ---
    def test_return_with_good_signature_switches_pro_on_once(self):
        from packs import billing
        p = self.buy()
        r = self.client.get("/v1/billing/return", self.back_params(p))
        self.assertEqual((r.status_code, r["Location"]), (302, "/#billing=paid"))
        until = billing.pro_until(self.user)
        self.assertTrue(billing.is_pro(self.user))
        self.client.get("/v1/billing/return", self.back_params(p))  # reload / replay
        self.assertEqual(billing.pro_until(self.user), until)  # days not added twice
        d = self.client.get("/v1/billing").json()
        self.assertEqual((d["plan"], d["limits"]["max_jobs"]), ("pro", 100))
        self.assertEqual(d["payments"][0]["status"], "paid")

    def test_return_with_forged_or_wrong_signature_does_nothing(self):
        from packs import billing
        p = self.buy()
        bad = self.back_params(p, secret="not-the-secret")
        self.assertEqual(self.client.get("/v1/billing/return", bad)["Location"], "/#billing=failed")
        tampered = self.back_params(p)
        tampered["razorpay_payment_id"] = "pay_other"
        self.assertEqual(self.client.get("/v1/billing/return", tampered)["Location"], "/#billing=failed")
        self.assertEqual(self.client.get("/v1/billing/return", {})["Location"], "/#billing=failed")
        self.assertFalse(billing.is_pro(self.user))

    def test_return_not_paid_is_pending_not_pro(self):
        from packs import billing
        p = self.buy()
        r = self.client.get("/v1/billing/return", self.back_params(p, status="created"))
        self.assertEqual(r["Location"], "/#billing=pending")
        self.assertFalse(billing.is_pro(self.user))

    def test_buying_again_adds_days_on_top(self):
        from packs import billing
        billing.grant(self.buy().pk, "pay_a")
        first = billing.pro_until(self.user)
        billing.grant(self.buy().pk, "pay_b")
        from datetime import timedelta
        self.assertEqual(billing.pro_until(self.user) - first, timedelta(days=30))

    # --- webhook ---
    def test_webhook_rejects_bad_or_missing_signature(self):
        p = self.buy()
        raw = json.dumps(self.paid_event(p)).encode()
        self.assertEqual(Client().post("/v1/billing/webhook", data=raw, content_type="application/json").status_code, 400)
        self.assertEqual(self.hook(self.paid_event(p), secret="wrong").status_code, 400)
        from packs import billing
        self.assertFalse(billing.is_pro(self.user))

    def test_webhook_paid_grants_once_even_if_sent_twice_and_after_return(self):
        from packs import billing
        p = self.buy()
        self.assertEqual(self.hook(self.paid_event(p)).status_code, 200)
        until = billing.pro_until(self.user)
        self.hook(self.paid_event(p))
        self.client.get("/v1/billing/return", self.back_params(p))
        self.assertEqual(billing.pro_until(self.user), until)
        p.refresh_from_db()
        self.assertEqual((p.status, p.payment_id), ("paid", "pay_222"))

    def test_webhook_wrong_amount_is_not_granted(self):
        from packs import billing
        p = self.buy()
        self.hook(self.paid_event(p, amount=100))
        p.refresh_from_db()
        self.assertEqual(p.status, "created")
        self.assertFalse(billing.is_pro(self.user))

    def test_webhook_unknown_link_and_odd_events_are_ignored(self):
        self.assertEqual(self.hook({"event": "payment_link.paid", "payload": {"payment_link": {"entity": {"id": "x", "reference_id": "y"}}, "payment": {"entity": {"id": "p", "amount": 1}}}}).status_code, 200)
        self.assertEqual(self.hook({"event": "something.else", "payload": {}}).status_code, 200)
        self.assertEqual(self.hook({"event": "payment_link.paid", "payload": {}}).status_code, 200)

    def test_refund_takes_the_days_back(self):
        from packs import billing
        p = self.buy()
        self.hook(self.paid_event(p))
        self.assertTrue(billing.is_pro(self.user))
        r = self.hook({"event": "refund.processed", "payload": {"refund": {"entity": {"payment_id": "pay_222"}}}})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(billing.is_pro(self.user))
        p.refresh_from_db()
        self.assertEqual(p.status, "refunded")
        self.hook({"event": "refund.processed", "payload": {"refund": {"entity": {"payment_id": "pay_222"}}}})  # twice is harmless
        self.assertFalse(billing.is_pro(self.user))

    def test_webhook_does_not_need_csrf_but_return_and_checkout_follow_rules(self):
        c = Client(enforce_csrf_checks=True)
        raw = b"{}"
        r = c.post("/v1/billing/webhook", data=raw, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=_sign(HOOK_SECRET, raw))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.post("/v1/billing/checkout", data="{}", content_type="application/json").status_code, 403)

    # --- ownership of data ---
    def test_export_and_admin_numbers(self):
        from django.contrib.auth import get_user_model
        p = self.buy()
        self.hook(self.paid_event(p))
        exp = self.client.get("/v1/me/export").json()
        self.assertEqual(exp["payments"][0]["razorpay_payment_id"], "pay_222")
        self.assertIsNotNone(exp["pro_until"])
        get_user_model().objects.filter(pk=self.user.pk).update(is_staff=True)
        money = self.client.get("/v1/admin/stats").json()["money"]
        self.assertEqual((money["paid_30d"], money["revenue_30d_paise"], money["pro_now"]), (1, 14900, 1))

    def test_payment_record_survives_account_deletion_without_the_person(self):
        from packs.models import Payment
        p = self.buy()
        self.hook(self.paid_event(p))
        self.user.delete()
        p.refresh_from_db()
        self.assertIsNone(p.user_id)
        self.assertEqual(Payment.objects.count(), 1)

    def test_grant_pro_command(self):
        from io import StringIO
        from django.core.management import call_command
        from packs import billing
        call_command("grant_pro", "pay@example.com", "10", stdout=StringIO())
        self.assertTrue(billing.is_pro(self.user))
        call_command("grant_pro", "pay@example.com", "0", stdout=StringIO())
        self.assertFalse(billing.is_pro(self.user))

    def test_ai_limit_is_per_plan(self):
        from packs import billing
        self.assertEqual(billing.limits_for(self.user)["ai_per_day"], 1)
        billing.grant(self.buy().pk, "pay_x")
        self.assertEqual(billing.limits_for(self.user)["plan"], "pro")


# ---------------- step 13: share link and LinkedIn help ----------------
SHARE_CV = """Aarti Sharma
aarti.secret@example.com | +91 98765 43210 | Mumbai
https://www.linkedin.com/in/aarti-sharma

EDUCATION
MCA, Mumbai University | 2024-2026

SKILLS
Python, Django, SQL

PROJECTS
ResumeWise: built a CV helper in Django; https://github.com/aarti/resumewise
"""


class ShareLinkApiTests(TestCase):
    PW = "Strong-pass-77x"

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client()
        post_json(self.client, "/v1/auth/register", {"email": "share@example.com", "password": self.PW, "name": "S", "accept_terms": True})
        r = post_json(self.client, "/v1/profiles", {"resume_text": SHARE_CV})
        self.assertEqual(r.status_code, 201, r.content)
        self.pid = r.json()["id"]
        self.url = "/v1/profiles/%s/share" % self.pid

    def put(self, body=None, client=None):
        return (client or self.client).put(self.url, data=json.dumps(body or {}), content_type="application/json")

    def test_off_by_default_and_turn_on(self):
        self.assertEqual(self.client.get(self.url).json(), {"shared": False, "path": None, "views": 0, "show_contact": False, "show_photo": False, "template": "classic"})
        r = self.put()
        self.assertEqual(r.status_code, 201)
        path = r.json()["path"]
        self.assertTrue(path.startswith("/s/"))
        self.assertGreaterEqual(len(path), 30)

    def test_public_page_hides_contact_by_default_and_has_safe_headers(self):
        path = self.put().json()["path"]
        page = Client().get(path)  # no login
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertIn("Aarti Sharma", html)
        self.assertIn("Python", html)
        self.assertIn("linkedin.com/in/aarti-sharma", html)  # links stay
        self.assertNotIn("aarti.secret@example.com", html)
        self.assertNotIn("98765", html)
        self.assertIn("noindex", page["X-Robots-Tag"])
        self.assertEqual(page["X-Frame-Options"], "DENY")
        self.assertEqual(page["Referrer-Policy"], "no-referrer")
        self.assertIn("default-src 'none'", page["Content-Security-Policy"])
        self.assertNotIn("<script", html.lower())

    def test_owner_can_show_contact(self):
        path = self.put({"show_contact": True}).json()["path"]
        html = Client().get(path).content.decode()
        self.assertIn("aarti.secret@example.com", html)
        self.assertIn("98765", html)

    def test_photo_only_when_chosen_and_template_has_one(self):
        from packs.models import Profile, ProfilePhoto
        ProfilePhoto.objects.create(profile=Profile.objects.get(id=self.pid), content_type="image/png", data=b"\x89PNG\r\n\x1a\n" + b"0" * 20)
        path = self.put({"template": "photo_header"}).json()["path"]
        self.assertNotIn("data:image/png", Client().get(path).content.decode())
        self.put({"show_photo": True})
        self.assertIn("data:image/png", Client().get(path).content.decode())

    def test_views_counted_and_turning_off_kills_the_link(self):
        path = self.put().json()["path"]
        Client().get(path)
        Client().get(path)
        self.assertEqual(self.client.get(self.url).json()["views"], 2)
        r = self.client.delete(self.url)
        self.assertFalse(r.json()["shared"])
        gone = Client().get(path)
        self.assertEqual(gone.status_code, 404)
        self.assertNotIn("Aarti", gone.content.decode())
        new_path = self.put().json()["path"]
        self.assertNotEqual(new_path, path)  # a fresh secret every time
        self.assertEqual(Client().get(path).status_code, 404)

    def test_updating_options_keeps_the_same_address(self):
        a = self.put().json()["path"]
        r = self.put({"show_contact": True, "template": "modern"})
        self.assertEqual((r.status_code, r.json()["path"], r.json()["template"]), (200, a, "modern"))

    def test_bad_inputs(self):
        self.assertEqual(self.put({"template": "nope"}).status_code, 400)
        self.assertEqual(self.put({"show_contact": "yes"}).status_code, 400)
        self.assertEqual(self.put({"show_photo": 1}).status_code, 400)

    def test_only_the_owner_manages_the_link(self):
        other = Client()
        post_json(other, "/v1/auth/register", {"email": "other-share@example.com", "password": self.PW, "name": "O", "accept_terms": True})
        self.assertEqual(other.get(self.url).status_code, 404)
        self.assertEqual(self.put(client=other).status_code, 404)
        self.assertEqual(other.delete(self.url).status_code, 404)
        self.assertEqual(Client().get(self.url).status_code, 401)

    def test_unknown_tokens_get_404_and_guessing_is_slowed(self):
        self.assertEqual(Client().get("/s/short").status_code, 404)
        from packs import share_views, throttle
        c = Client()
        for _ in range(throttle.ip_limit(share_views.PUBLIC_FAILS)):
            c.get("/s/" + "x" * 32)
        self.assertEqual(c.get("/s/" + "y" * 32).status_code, 429)

    def test_expired_cv_link_stops_working(self):
        from datetime import timedelta
        from django.utils import timezone
        from packs.models import Profile
        path = self.put().json()["path"]
        Profile.objects.filter(id=self.pid).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(Client().get(path).status_code, 404)

    def test_deleting_the_cv_deletes_the_link(self):
        path = self.put().json()["path"]
        self.client.delete("/v1/profiles/%s" % self.pid)
        self.assertEqual(Client().get(path).status_code, 404)

    def test_edits_show_on_the_shared_page(self):
        path = self.put().json()["path"]
        self.client.post("/v1/profiles/%s/items" % self.pid, data=json.dumps({"section": "skills", "text": "Docker"}), content_type="application/json")
        self.assertIn("Docker", Client().get(path).content.decode())


class LinkedinApiTests(ShareLinkApiTests):
    def test_linkedin_advice(self):
        r = self.client.get("/v1/profiles/%s/linkedin" % self.pid, {"target": "Software Developer"})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["headlines"][0]["text"].startswith("Software Developer"))
        self.assertEqual(d["skills"][:3], ["Python", "Django", "SQL"])
        self.assertEqual(d["featured"][0]["links"], ["https://github.com/aarti/resumewise"])
        self.assertIn("MCA", d["about"])
        self.assertNotIn("aarti.secret@example.com", json.dumps(d))

    def test_linkedin_rules(self):
        self.assertEqual(self.client.get("/v1/profiles/%s/linkedin" % self.pid, {"target": "x" * 81}).status_code, 400)
        self.assertEqual(Client().get("/v1/profiles/%s/linkedin" % self.pid).status_code, 401)
        other = Client()
        post_json(other, "/v1/auth/register", {"email": "other-li@example.com", "password": self.PW, "name": "O", "accept_terms": True})
        self.assertEqual(other.get("/v1/profiles/%s/linkedin" % self.pid).status_code, 404)
