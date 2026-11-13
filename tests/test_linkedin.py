"""LinkedIn help built from CV facts. Run: python3 -m unittest tests.test_linkedin"""
import unittest

from core import linkedin, resume_parser

CV = """Aarti Sharma
aarti@example.com | +91 98765 43210 | Mumbai
https://www.linkedin.com/in/aarti-sharma

EDUCATION
MCA, Mumbai University | 2024-2026 | 8.1 CGPA

SKILLS
Languages: Python, JavaScript | Tools: Git, Docker
Databases: SQL, SQLite

PROJECTS
ResumeWise: built a CV helper in Django and React; https://github.com/aarti/resumewise
Event site: made a college event website for 300 students
"""
EMPTY = "Raj Kumar\nraj@example.com\n"


class LinkedinTests(unittest.TestCase):
    def setUp(self):
        self.p = resume_parser.parse_resume(CV)

    def test_skills_come_from_the_cv_without_labels(self):
        sk = linkedin.skills(self.p)
        self.assertEqual(sk[:4], ["Python", "JavaScript", "Git", "Docker"])
        self.assertNotIn("Languages", " ".join(sk))
        self.assertEqual(len(sk), len({s.lower() for s in sk}))

    def test_headlines_use_only_cv_facts_and_the_typed_role(self):
        heads = linkedin.headlines(self.p, "Software Developer")
        self.assertTrue(heads)
        allowed = set(w.lower() for w in linkedin.skills(self.p)) | {"software developer", "mca", "open to software developer roles", "mumbai"}
        for h in heads:
            self.assertLessEqual(len(h["text"]), linkedin.HEADLINE_LIMIT)
            for part in h["text"].replace(" and ", " | ").split(" | "):
                self.assertIn(part.strip().lower(), allowed, h["text"])
        self.assertTrue(heads[0]["text"].startswith("Software Developer"))

    def test_headline_without_target_does_not_invent_a_role(self):
        for h in linkedin.headlines(self.p):
            self.assertNotIn("Developer", h["text"])
            self.assertNotIn("Open to", h["text"])

    def test_headline_is_clipped_to_the_limit(self):
        long = resume_parser.parse_resume("A B\nSKILLS\n" + ", ".join("Skill%02d%s" % (i, "x" * 30) for i in range(12)) + "\n")
        for h in linkedin.headlines(long, "T" * 60):
            self.assertLessEqual(len(h["text"]), 220)

    def test_about_quotes_cv_lines_only(self):
        text = linkedin.about(self.p, "Backend Developer")
        self.assertIn("MCA, Mumbai University", text)
        self.assertIn("Python, JavaScript, Git, Docker", text)
        self.assertIn("made a college event website for 300 students", text)
        self.assertIn("I am looking for Backend Developer roles", text)
        self.assertNotIn("Kubernetes", text)
        self.assertNotIn("aarti@example.com", text)  # contact details are not put in the About text
        self.assertNotIn("I am looking for", linkedin.about(self.p))

    def test_featured_finds_project_links(self):
        f = linkedin.featured(self.p)
        self.assertEqual(f[0]["title"], "ResumeWise")
        self.assertEqual(f[0]["links"], ["https://github.com/aarti/resumewise"])
        self.assertEqual(f[1]["links"], [])

    def test_checklist_knows_about_the_linkedin_link_and_handle(self):
        texts = " ".join(c["text"] for c in linkedin.checklist(self.p))
        self.assertIn("already has your LinkedIn address", texts)
        self.assertIn("linkedin.com/in/aarti-sharma", texts)

    def test_sparse_cv_gets_todo_hints_not_made_up_content(self):
        sparse = resume_parser.parse_resume(EMPTY)
        advice = linkedin.advise(sparse, "")
        self.assertEqual((advice["headlines"], advice["skills"], advice["featured"]), ([], [], []))
        self.assertEqual(advice["about"], "")
        texts = " ".join(c["text"] for c in advice["checklist"])
        self.assertIn("no Skills section", texts)
        self.assertIn("Add your LinkedIn address", texts)


if __name__ == "__main__":
    unittest.main()
