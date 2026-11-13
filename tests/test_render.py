import unittest

from core import render, resume_parser

from tests.test_image_check import make_jpeg, make_png

RESUME = """Aarti Sharma
Junior QA Engineer
aarti@example.com | +91 98765 43210 | linkedin.com/in/aarti

SUMMARY
MCA graduate focused on manual testing.

EXPERIENCE
- Tested 12 web modules and logged 60+ defects

PROJECTS
- Wrote test cases for login pages

SKILLS
- Jira, Postman, SQL

EDUCATION
- MCA, University of Mumbai, 2026
"""


def parsed():
    return resume_parser.parse_resume(RESUME)


class RenderTests(unittest.TestCase):
    def test_every_template_renders_the_content(self):
        for tid in render.TEMPLATES:
            page = render.render_resume_html(parsed(), tid)
            for text in ("Aarti Sharma", "aarti@example.com", "Tested 12 web modules", "MCA, University of Mumbai"):
                self.assertIn(text, page, "%s missing in %s" % (text, tid))
            self.assertTrue(page.startswith("<!doctype html>"))

    def test_text_is_escaped(self):
        p = parsed()
        p["header"][0] = "<script>alert</script>"
        p["sections"][0]["items"][0]["text"] = "<img src=x onerror=alert(2)>"
        for tid in render.TEMPLATES:
            page = render.render_resume_html(p, tid)
            self.assertNotIn("<script>alert<", page)
            self.assertNotIn("<img src=x", page)
            self.assertIn("&lt;script&gt;", page)

    def test_photo_only_appears_in_photo_templates(self):
        photo = {"content_type": "image/png", "data": make_png()}
        for tid, meta in render.TEMPLATES.items():
            page = render.render_resume_html(parsed(), tid, photo)
            self.assertEqual("data:image/png;base64," in page, meta["photo"], tid)

    def test_initials_when_no_photo(self):
        page = render.render_resume_html(parsed(), "photo_header")
        self.assertIn("ph-empty", page)
        self.assertIn(">AS<", page)

    def test_bad_photo_type_and_unknown_template(self):
        with self.assertRaises(ValueError):
            render.render_resume_html(parsed(), "photo_header", {"content_type": "image/svg+xml", "data": b"x"})
        with self.assertRaises(ValueError):
            render.render_resume_html(parsed(), "nope")

    def test_role_is_taken_from_header_but_not_contact_lines(self):
        self.assertIn("Junior QA Engineer", render.render_resume_html(parsed(), "modern"))
        p = parsed()
        p["header"] = ["Aarti Sharma", "aarti@example.com | +91 98765 43210"]
        self.assertNotIn("class='role'", render.render_resume_html(p, "modern"))

    def test_edited_contact_is_used(self):
        from core import profile_edit
        p = profile_edit.set_contact(parsed(), email="new@example.com")
        page = render.render_resume_html(p, "classic")
        self.assertIn("new@example.com", page)
        self.assertNotIn("aarti@example.com", page)

    def test_empty_resume_does_not_crash(self):
        empty = {"header": [], "sections": []}
        for tid in render.TEMPLATES:
            self.assertIn("Your Name", render.render_resume_html(empty, tid))

    def test_location_and_bare_links_are_shown(self):
        text = ("Aarti Sharma\nMumbai, Maharashtra | aarti@example.com | linkedin.com/in/aarti\n\nPROJECTS\n- Tested modules\n")
        for tid in render.TEMPLATES:
            page = render.render_resume_html(resume_parser.parse_resume(text), tid)
            self.assertIn("Mumbai, Maharashtra", page, tid)
            self.assertIn("linkedin.com/in/aarti", page, tid)

    def test_list_templates(self):
        items = render.list_templates()
        self.assertEqual([i["id"] for i in items], list(render.TEMPLATES))
        self.assertEqual(sum(1 for i in items if i["photo"]), 2)
        by_id = {i["id"]: i for i in items}
        self.assertTrue(by_id["photo_header"]["ats_friendly"])
        self.assertFalse(by_id["photo_sidebar"]["ats_friendly"])
        self.assertTrue(all(i["ats_friendly"] for i in items if not i["photo"]))


if __name__ == "__main__":
    unittest.main()
