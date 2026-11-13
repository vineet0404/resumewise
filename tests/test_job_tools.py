"""Tests for job matching, cover letter and interview questions (core/job_match.py, cover_letter.py, interview.py)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import cover_letter, cv_builder, interview, job_match, keywords  # noqa: E402

CV = cv_builder.build({
    "contact": {"name": "Aarti Sharma", "email": "aarti@example.com", "phone": "+91 98200 11122"},
    "education": [{"degree": "MCA", "school": "Mumbai University", "years": "2024-2026"}],
    "skills": [{"items": "Python, Django, SQL"}],
    "projects": [{"title": "ResumeWise", "points": ["Wrote 254 test cases", "Built REST APIs in Django"]}],
})
JD = "Python developer. Must have experience with Django and REST APIs. Knowledge of Docker is required. You will write test cases."


class JobTools(unittest.TestCase):
    def test_match_names_are_readable_and_have_evidence(self):
        a = job_match.analyse(CV, JD)
        covered = {c["name"]: c["line"] for c in a["covered"]}
        self.assertEqual(covered["REST APIs"], "Built REST APIs in Django")
        self.assertIn("Docker", [m["name"] for m in a["missing"]])
        self.assertTrue(all(m["required"] for m in a["missing"] if m["name"] == "Docker"))

    def test_html_tags_in_the_job_text_are_ignored(self):
        a = job_match.analyse(CV, JD + " <b>x</b> <script>y</script>")
        names = " ".join(m["name"] for m in a["missing"])
        self.assertNotIn("script", names)
        self.assertNotIn("<", names)

    def test_score_cannot_be_raised_by_wording(self):
        before = job_match.analyse(CV, JD)["score"]
        after = job_match.analyse(CV, JD + " " + JD)["score"]
        self.assertLessEqual(abs(before - after), 15)

    def test_cover_letter_only_quotes_cv_and_skips_missing(self):
        a = job_match.analyse(CV, JD)
        r = cover_letter.write(CV, a, "Python Developer", "Acme", why="I like testing.", manager="Ms Rao")
        t = r["text"]
        self.assertTrue(t.startswith("Dear Ms Rao,"))
        self.assertIn("Built REST APIs in Django", t)
        self.assertIn("I like testing.", t)
        self.assertNotIn("Docker", t)
        self.assertEqual(r["left_out"], ["Docker"])
        plain = cover_letter.write(CV, a, "", "")["text"]
        self.assertIn("Dear Hiring Manager,", plain)
        self.assertIn("the open position", plain)

    def test_cover_letter_has_no_repeated_line(self):
        a = job_match.analyse(CV, JD)
        t = cover_letter.write(CV, a, "Dev")["text"]
        bullets = [ln for ln in t.splitlines() if ln.startswith("- ")]
        self.assertEqual(len(bullets), len(set(bullets)))

    def test_interview_questions(self):
        a = job_match.analyse(CV, JD)
        qs = interview.questions(CV, a, "Python Developer", "Acme")
        ids = [q["id"] for q in qs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLessEqual(len(qs), interview.MAX_QUESTIONS)
        self.assertEqual(qs[0]["id"], "intro")
        self.assertEqual(qs[0]["cv_line"], "MCA | Mumbai University | 2024-2026")
        gap = [q for q in qs if q["kind"] == "gap"]
        self.assertEqual(len(gap), 1)
        self.assertIn("Never claim it", gap[0]["tip"])
        self.assertEqual(gap[0]["cv_line"], "")
        for q in qs:
            self.assertTrue(q["question"] and q["tip"])

    def test_original_forms(self):
        self.assertEqual(keywords.original_forms(["test case", "rest apis"], "Write Test Cases for REST APIs"),
                         {"test case": "Test Cases", "rest apis": "REST APIs"})


if __name__ == "__main__":
    unittest.main()
