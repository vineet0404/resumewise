import io
import unittest
import zipfile
import xml.etree.ElementTree as ET

from core import docx_export, extract, resume_parser


class UploadCleanupTests(unittest.TestCase):
    def test_wrapped_lines_are_joined_but_bullets_and_headings_are_not(self):
        long1 = "Built a booking system with Python and Django and tested seat booking and payment"
        text = "\n".join(["Aarti Sharma", "PROJECTS", long1, "pages with many cases.", "- Found 14 bugs.", "SKILLS"])
        out = extract._unwrap(text)
        self.assertIn(long1 + " pages with many cases.", out)
        self.assertIn("\n- Found 14 bugs.", out)
        self.assertIn("\nSKILLS", out)
        self.assertTrue(out.startswith("Aarti Sharma\nPROJECTS"))

    def test_date_range_broken_after_dash_is_rejoined(self):
        text = "x" * 60 + "\nMCA, University of Mumbai, 2024 -\n2026\nBSc, 2021 - 2024"
        self.assertIn("2024 - 2026", extract._unwrap(text))

    def test_ligatures_and_odd_spaces_fixed(self):
        self.assertEqual(extract._clean_chars("\ufb01nance\u00a0of\u00ad\u200b\ufb02ow"), "finance offlow")

    def test_contact_heading_goes_to_header(self):
        p = resume_parser.parse_resume("Aarti\nSKILLS\n- Jira\nCONTACT\naarti@example.com\nEDUCATION\n- MCA 2026")
        self.assertIn("aarti@example.com", p["header"] + [])  # joins header, not a section
        self.assertEqual([s["key"] for s in p["sections"]], ["skills", "education"])


class DocxExportTests(unittest.TestCase):
    PARSED = {"header": ["Aarti <Sharma> & Co", "a@b.com | +91 98765 43210"],
              "sections": [{"key": "summary", "title": "SUMMARY", "items": [{"id": "summary.1", "text": "QA \x00person"}]},
                           {"key": "skills", "title": "SKILLS", "items": [{"id": "skills.1", "text": "Jira & SQL"}]},
                           {"key": "empty", "title": "EMPTY", "items": []}]}

    def test_valid_zip_and_xml_parts(self):
        data = docx_export.build_docx(self.PARSED)
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertIsNone(z.testzip())
        for name in z.namelist():
            ET.fromstring(z.read(name))  # every part is well formed

    def test_round_trip_and_special_characters(self):
        text = extract.extract_text("r.docx", docx_export.build_docx(self.PARSED))
        self.assertIn("Aarti <Sharma> & Co", text)
        self.assertIn("QA person", text)
        self.assertIn("- Jira & SQL", text)
        self.assertNotIn("EMPTY", text)

    def test_empty_resume_does_not_crash(self):
        self.assertTrue(docx_export.build_docx({"header": [], "sections": []}).startswith(b"PK"))


class UnwrapSafetyTests(unittest.TestCase):
    def test_label_lines_are_not_joined(self):
        wide = "x" * 100
        text = wide + "\n" + "Testing: manual testing, test cases, defect reporting, regression te" + "\nTools: Jira, Postman"
        self.assertEqual(extract._unwrap(text).count("\n"), 2)

    def test_pdf_round_trip_of_every_template(self):
        """Uses the real template PDFs when they exist (made in the project's scratch area)."""
        import os
        base = os.environ.get("TEMPLATE_PDF_DIR")
        if not base:
            self.skipTest("set TEMPLATE_PDF_DIR to a folder with the template PDFs and resume.txt")
        src = resume_parser.parse_resume(open(os.path.join(base, "resume.txt")).read())
        want = [(s["key"], [i["text"] for i in s["items"]]) for s in src["sections"]]
        for name in ("classic", "modern", "compact", "photo_header", "photo_sidebar"):
            text = extract.extract_text(name + ".pdf", open(os.path.join(base, name + ".pdf"), "rb").read())
            got = resume_parser.parse_resume(text)
            self.assertEqual([(s["key"], [i["text"] for i in s["items"]]) for s in got["sections"]], want, name)


class TailoredCvTests(unittest.TestCase):
    BASE = {"header": ["Aarti Sharma", "aarti@example.com"], "sections": []}
    OUT = {"sections": [{"type": "projects", "bullets": [{"text": "A"}, {"text": "B"}]},
                        {"type": "hobbies", "bullets": [{"text": "C"}]}]}

    def test_removed_lines_and_empty_sections_are_dropped_and_contact_kept(self):
        from core import tailored_cv
        r = tailored_cv.build_resume(self.BASE, self.OUT, {"s0.b0": "removed", "s1.b0": "removed"})
        self.assertEqual([s["key"] for s in r["sections"]], ["projects"])
        self.assertEqual([i["text"] for i in r["sections"][0]["items"]], ["B"])
        self.assertEqual(r["sections"][0]["items"][0]["id"], "projects.1")
        self.assertEqual(r["header"][0], "Aarti Sharma")
        self.assertEqual(r["sections"][0]["title"], "PROJECTS")

    def test_unknown_section_gets_a_readable_title_and_pending_new_is_found(self):
        from core import tailored_cv
        r = tailored_cv.build_resume(self.BASE, self.OUT, {})
        self.assertEqual(r["sections"][1]["title"], "Hobbies")
        claims = [{"line_ref": "s0.b0", "label": "supported"}, {"line_ref": "s0.b1", "label": "new"}]
        self.assertEqual(tailored_cv.pending_new(claims, {}), ["s0.b1"])
        self.assertEqual(tailored_cv.pending_new(claims, {"s0.b1": "confirmed"}), [])


class RealWorldWordFileTests(unittest.TestCase):
    """A Word file shaped like a college CV: text boxes, a fallback copy of each shape, a page header."""

    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    MC = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'

    def _docx(self):
        def p(t):
            return "<w:p><w:r><w:t>%s</w:t></w:r></w:p>" % t
        box = ("<w:r><mc:AlternateContent><mc:Choice><w:drawing><w:txbxContent>%s%s</w:txbxContent></w:drawing></mc:Choice>"
               "<mc:Fallback><w:pict><w:txbxContent>%s%s</w:txbxContent></w:pict></mc:Fallback></mc:AlternateContent></w:r>"
               % (p("Institute Address: Thakur Institute, Mumbai 400101."), p("Phone Nos: 022-28840484"),
                  p("Institute Address: Thakur Institute, Mumbai 400101."), p("Phone Nos: 022-28840484")))
        body = ("<w:p>%s</w:p>" % box) + p("MCA Batch (2023-25)") + p("Vineet Singh") + p("SKILLS") + p("Python, Django")
        doc = '<w:document %s %s><w:body>%s</w:body></w:document>' % (self.W, self.MC, body)
        header = '<w:hdr %s><w:p><w:r><w:t>vineet@example.com | +91 98765 43210</w:t></w:r></w:p></w:hdr>' % self.W
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("word/document.xml", doc)
            z.writestr("word/header1.xml", header)
        return out.getvalue()

    def test_shapes_are_not_duplicated_or_glued_together(self):
        text = extract.extract_text("cv.docx", self._docx())
        self.assertEqual(text.count("Institute Address"), 1)
        self.assertEqual(text.count("Phone Nos"), 1)
        self.assertEqual(text.count("Vineet Singh"), 1)
        self.assertNotIn("400101.Phone", text)

    def test_page_header_contact_is_kept_and_name_is_found(self):
        from core import profile_edit
        text = extract.extract_text("cv.docx", self._docx())
        self.assertIn("vineet@example.com", text)
        parsed = resume_parser.parse_resume(text)
        self.assertEqual(profile_edit.guess_name(parsed["header"]), "Vineet Singh")
        self.assertEqual(profile_edit.with_contact(parsed)["contact"]["email"], "vineet@example.com")
        out = extract.extract_text("o.docx", docx_export.build_docx(parsed))
        self.assertTrue(out.startswith("Vineet Singh"))

    def test_name_guess_rules(self):
        from core import profile_edit as pe
        self.assertEqual(pe.guess_name(["Aarti Sharma", "Junior QA"]), "Aarti Sharma")
        self.assertEqual(pe.guess_name(["Vineet", "a@b.com"]), "Vineet")
        self.assertEqual(pe.guess_name(["Curriculum Vitae", "Rahul Verma"]), "Rahul Verma")
        self.assertEqual(pe.guess_name([]), "")
        edited = pe.set_contact({"header": ["Institute Address: x"], "sections": []}, name="  Vineet   Singh ")
        self.assertEqual(edited["contact"]["name"], "Vineet Singh")
        self.assertEqual(pe.name_and_role(edited)[0], "Vineet Singh")


class RealCvDetailsTests(unittest.TestCase):
    def test_letterhead_contact_is_not_used_and_name_is_not_repeated_as_role(self):
        from core import profile_edit as pe
        header = ["Institute Address: Thakur Institute, Mumbai 400101.", "E-mail ID: timscdr.tnp@thakureducation.orgInstitute",
                  "Vineet Singh", "Vineet Singh", "+918433582918 | https://github.com/vineet0404/x | www.linkedin.com/in/vineet-singh04"]
        parsed = {"header": header, "sections": []}
        c = pe.with_contact(parsed)["contact"]
        self.assertEqual(c["name"], "Vineet Singh")
        self.assertEqual(c["email"], "")
        self.assertIn("8433582918", c["phone"])
        self.assertEqual(pe.name_and_role(parsed)[1], "")

    def test_email_stops_before_glued_text(self):
        from core import profile_edit as pe
        self.assertEqual(pe._EMAIL.search("x a@b.orgInstitute y").group(0), "a@b.org")
        self.assertEqual(pe._EMAIL.search("A@B.COM").group(0), "A@B.COM")
        self.assertEqual(pe._EMAIL.search("me@site.co.in").group(0), "me@site.co.in")

    def test_more_heading_names_are_understood(self):
        text = "\n".join(["Vineet", "ACADEMIC QUALIFICATIONS", "- BSc IT 2022", "PROJECTS UNDERTAKEN",
                          "- College Feedback System", "Hobbies", "- Chess"])
        p = resume_parser.parse_resume(text)
        self.assertEqual([s["key"] for s in p["sections"]], ["education", "projects", "interests"])


class RealCvShapeTests(unittest.TestCase):
    TEXT = "\n".join([
        "Vineet Singh", "Plot no.255/C-5, Anmol C.H.S., near Pragati School, Gorai-2, Borivali-west", "+918433582918",
        "EDUCATION", "- MCA 2025", "SKILLS", "Programming Languages:", "Java, Python", "Databases:", "MySql", "SQL",
        "CO-CURRICULAR AND EXTRA-CURRICULAR ACTIVITIES", "- Manager of DLLE Program",
        "ABOUT ME", "Date of Birth: 04/04/2001", "Gender: Male", "LANGUAGES KNOWN", "English", "Hindi"])

    def test_labels_long_headings_and_personal_details(self):
        from core import profile_edit
        p = resume_parser.parse_resume(self.TEXT)
        keys = [s["key"] for s in p["sections"]]
        self.assertEqual(keys, ["education", "skills", "achievements", "personal", "languages"])
        skills = [i["text"] for i in p["sections"][1]["items"]]
        self.assertEqual(skills, ["Programming Languages: Java, Python", "Databases: MySql, SQL"])
        self.assertIn("Borivali-west", profile_edit.with_contact(p)["contact"]["location"])

    def test_personal_details_are_never_sent_to_the_ai(self):
        import json
        from core import gateway, tailor_service
        p = resume_parser.parse_resume(self.TEXT)
        reply = json.dumps({"sections": [{"type": "education", "bullets": [
            {"text": "MCA 2025", "source_id": "education.1", "change": "kept", "keywords_used": []}]}], "gaps": []})
        fake = gateway.FakeProvider([reply])
        tailor_service.tailor(p, "Need Java", gateway.Gateway({"tailor": fake}))
        sent = fake.calls[0]["user"]
        self.assertNotIn("04/04/2001", sent)
        self.assertNotIn("Gender", sent)
        self.assertIn("MCA 2025", sent)
