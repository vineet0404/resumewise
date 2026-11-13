"""Tests for the "Build from scratch" builder (core/cv_builder.py)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import cv_builder, profile_edit, render  # noqa: E402
from core.profile_edit import EditError  # noqa: E402

FULL = {
    "contact": {"name": "Aarti Sharma", "email": "aarti@example.com", "phone": "+91 98200 11122", "location": "Thane", "links": ["linkedin.com/in/aarti"]},
    "role": "Python Developer",
    "summary": "MCA student.",
    "education": [{"degree": "MCA", "school": "Mumbai University", "years": "2024-2026", "score": "CGPA 8.2"}],
    "skills": [{"group": "Languages", "items": "Python, SQL"}, {"items": "Git"}],
    "projects": [{"title": "ResumeWise", "tech": "Django", "points": ["Built a parser", "Wrote tests"]}],
    "experience": [{"role": "Tester Intern", "company": "Acme", "dates": "2025", "points": "Tested modules\nLogged bugs"}],
    "certifications": ["Python course"], "achievements": "Hackathon winner", "languages": ["English", "Hindi"],
}


def texts(parsed):
    return {s["key"]: [i["text"] for i in s["items"]] for s in parsed["sections"]}


class BuilderTests(unittest.TestCase):
    def test_every_line_is_what_the_person_typed(self):
        t = texts(cv_builder.build(FULL))
        self.assertEqual(t["education"], ["MCA | Mumbai University | 2024-2026 | CGPA 8.2"])
        self.assertEqual(t["skills"], ["Languages: Python, SQL", "Git"])
        self.assertEqual(t["projects"], ["ResumeWise | Django", "Built a parser", "Wrote tests"])
        self.assertEqual(t["experience"], ["Tester Intern | Acme | 2025", "Tested modules", "Logged bugs"])
        self.assertEqual(t["achievements"], ["Hackathon winner"])
        self.assertEqual(t["summary"], ["MCA student."])

    def test_empty_parts_make_no_sections(self):
        p = cv_builder.build({"contact": {"name": "Ravi Kumar"}, "skills": [{"items": "Excel"}], "projects": [{}], "education": [{"degree": " "}]})
        self.assertEqual([s["key"] for s in p["sections"]], ["skills"])

    def test_ids_are_unique_and_editable(self):
        p = cv_builder.build(FULL)
        ids = [i["id"] for s in p["sections"] for i in s["items"]]
        self.assertEqual(len(ids), len(set(ids)))
        new = profile_edit.edit_item(p, "skills.1", "Languages: Python")
        self.assertIn("Languages: Python", texts(new)["skills"])

    def test_result_works_with_render_and_ats(self):
        p = cv_builder.build(FULL)
        for tpl in ("classic", "modern", "compact"):
            html = render.render_resume_html(p, tpl)
            self.assertIn("Aarti Sharma", html)
            self.assertIn("Wrote tests", html)

    def test_html_is_escaped_in_the_page(self):
        p = cv_builder.build(dict(FULL, summary="<script>alert(1)</script>"))
        self.assertNotIn("<script>alert(1)", render.render_resume_html(p, "classic"))

    def test_refusals(self):
        bad = [None, [], {}, {"contact": "x"}, {"contact": {"name": " "}, "skills": [{"items": "x"}]}, {"contact": {"name": "A B"}},
               {"contact": {"name": "A B"}, "skills": "x", "projects": [{"points": ["p"]}]},
               {"contact": {"name": "A B", "email": "nope"}, "skills": "x"},
               {"contact": {"name": "A B"}, "education": "text"}, {"contact": {"name": "A B"}, "skills": [5]},
               {"contact": {"name": "A B"}, "skills": [{"items": 5}]},
               {"contact": {"name": "A B"}, "summary": "y" * 401},
               {"contact": {"name": "A B"}, "projects": [{"title": "t"}] * 9},
               {"contact": {"name": "A B"}, "projects": [{"title": "t", "points": ["p"] * 9}]},
               {"contact": {"name": "A B"}, "languages": ["x"] * 16}]
        for data in bad:
            with self.assertRaises(EditError, msg=str(data)[:60]):
                cv_builder.build(data)

    def test_input_is_not_changed(self):
        import copy
        before = copy.deepcopy(FULL)
        cv_builder.build(FULL)
        self.assertEqual(before, FULL)


if __name__ == "__main__":
    unittest.main()
