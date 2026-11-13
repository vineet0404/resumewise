import unittest

from core import ats, render, resume_parser

from tests.test_image_check import make_png

TEXT = """Aarti Sharma
Junior QA Engineer
Mumbai, Maharashtra | aarti.sharma@example.com | +91 98765 43210 | linkedin.com/in/aarti-sharma

SUMMARY
MCA graduate with practice in manual testing and defect reporting.

EXPERIENCE
- QA Intern, Finserve Technologies (Jun 2025 - Dec 2025)
- Tested 12 web modules and logged 60+ defects in Jira.

PROJECTS
- Online Bus Booking System built with Python and Django.

SKILLS
- Testing: manual testing, test cases
- Tools: Jira, Postman

EDUCATION
- MCA, University of Mumbai, 2024 - 2026
"""


def parsed():
    return resume_parser.parse_resume(TEXT)


class TemplateScannerTests(unittest.TestCase):
    def test_every_template_reads_cleanly(self):
        photo = {"content_type": "image/png", "data": make_png()}
        for tid in render.TEMPLATES:
            result = ats.check_resume(parsed(), tid, photo)
            bad = [f for f in result["findings"] if f["level"] in (ats.ERROR, ats.WARN)]
            self.assertEqual(bad, [], tid)
            self.assertGreaterEqual(result["score"], 90, tid)

    def test_name_is_first_text_in_every_template(self):
        for tid in render.TEMPLATES:
            lines = ats.html_text_lines(render.render_resume_html(parsed(), tid))
            self.assertEqual(lines[0], "Aarti Sharma", tid)

    def test_headings_keep_resume_order_in_every_template(self):
        for tid in render.TEMPLATES:
            lines = ats.html_text_lines(render.render_resume_html(parsed(), tid))
            keys = [s["key"] for s in resume_parser.parse_resume("\n".join(lines))["sections"]]
            self.assertEqual(keys, ["summary", "experience", "projects", "skills", "education"], tid)

    def test_no_letter_spacing_on_any_template(self):
        for tid in render.TEMPLATES:
            self.assertNotIn("letter-spacing", render.render_resume_html(parsed(), tid), tid)

    def test_no_tables_scripts_or_external_links(self):
        for tid in render.TEMPLATES:
            page = render.render_resume_html(parsed(), tid).lower()
            for bad in ("<table", "<script", "http://", "https://", "<iframe"):
                self.assertNotIn(bad, page, "%s contains %s" % (tid, bad))


class TextCheckTests(unittest.TestCase):
    def test_good_resume_scores_high(self):
        self.assertGreaterEqual(ats.check_text(TEXT)["score"], 95)

    def test_spaced_headings_are_an_error(self):
        spaced = TEXT.replace("SUMMARY", "S U M M A R Y").replace("EXPERIENCE", "E X P E R I E N C E")
        result = ats.check_text(spaced)
        self.assertIn("spaced_headings", [f["code"] for f in result["findings"]])
        self.assertLess(result["score"], 90)

    def test_missing_contact_and_sections(self):
        result = ats.check_text("Aarti Sharma\nI like testing.\n")
        codes = [f["code"] for f in result["findings"]]
        for code in ("no_sections", "no_email", "no_phone"):
            self.assertIn(code, codes)
        self.assertLessEqual(result["score"], 50)

    def test_name_not_first(self):
        text = "CONTACT\n" + TEXT
        codes = [f["code"] for f in ats.check_text(text)["findings"]]
        self.assertIn("name_not_first", codes)

    def test_icons_and_empty(self):
        codes = [f["code"] for f in ats.check_text(TEXT.replace("Mumbai", "☎ Mumbai"))["findings"]]
        self.assertIn("icons", codes)
        self.assertEqual(ats.check_text("")["score"], 80)

    def test_sidebar_template_gets_an_info_note(self):
        codes = [f["code"] for f in ats.check_resume(parsed(), "photo_sidebar")["findings"]]
        self.assertIn("two_columns", codes)


if __name__ == "__main__":
    unittest.main()


class LongResumeSidebarTests(unittest.TestCase):
    def test_contact_stays_near_the_top_even_for_a_long_resume(self):
        from core import ats, resume_parser
        lines = ["Aarti Sharma", "aarti@example.com", "+91 98765 43210", "", "EXPERIENCE"]
        lines += ["- Tested module %d with 12 test cases in 2025." % i for i in range(1, 25)]
        lines += ["", "SKILLS", "- Jira", "", "EDUCATION", "- MCA, Mumbai, 2026"]
        parsed = resume_parser.parse_resume("\n".join(lines))
        parsed["contact"] = {"email": "aarti@example.com", "phone": "+91 98765 43210", "links": [], "location": "Mumbai"}
        report = ats.check_resume(parsed, "photo_sidebar")
        codes = [f["code"] for f in report["findings"]]
        self.assertNotIn("no_email", codes)
        self.assertNotIn("no_phone", codes)
        self.assertGreaterEqual(report["score"], 90)
