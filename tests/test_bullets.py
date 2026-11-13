"""Tests for the line checker (core/bullets.py): it points and asks, it never invents."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import bullets, cv_builder  # noqa: E402


def codes(text, section="experience"):
    return [t["code"] for t in bullets.check_line(text, section)]


class BulletTests(unittest.TestCase):
    def test_weak_starts(self):
        for text in ("Worked on testing of web modules", "Responsible for the database", "Helped with deployment", "Assisted in a survey of 20 users"):
            self.assertIn("weak_start", codes(text), text)
        self.assertNotIn("weak_start", codes("Tested 12 web modules"))

    def test_questions_never_contain_made_up_numbers(self):
        for tip in bullets.check_line("Tested web modules for the team", "projects"):
            for key in ("tip",):
                self.assertFalse(any(ch.isdigit() for ch in tip[key]))
            for ask in tip.get("asks", []):
                self.assertTrue(ask.endswith("?"))
                self.assertFalse(any(ch.isdigit() for ch in ask))

    def test_number_present_means_no_number_tip(self):
        self.assertNotIn("no_number", codes("Wrote 254 test cases for the billing module"))
        self.assertNotIn("no_number", codes("Cut load time by 30% on the home page"))
        self.assertIn("no_number", codes("Wrote test cases for the billing module"))

    def test_first_person_passive_vague_short_long(self):
        self.assertIn("first_person", codes("I built a login page with 3 forms"))
        self.assertIn("passive", codes("The module was tested for 2 weeks by the team"))
        self.assertIn("vague", codes("Handled various tasks etc"))
        self.assertIn("too_short", codes("Did testing", "projects"))
        self.assertIn("too_long", codes(" ".join(["word"] * 35)))

    def test_sections_that_are_not_sentences_are_left_alone(self):
        for section in ("skills", "education", "languages", "certifications"):
            self.assertEqual(codes("Worked on Python, Django, SQL", section), [])

    def test_other_scripts_are_left_alone(self):
        self.assertEqual(codes("टेस्टिंग पर काम किया"), [])
        self.assertEqual(codes("వెబ్ మాడ్యూల్స్ పరీక్షించాను"), [])

    def test_empty_and_unknown(self):
        self.assertEqual(bullets.check_line("", "projects"), [])
        self.assertEqual(bullets.check_line(None, "projects"), [])
        self.assertEqual(bullets.check_line("Worked on x", "nope"), [])

    def test_repeated_starts(self):
        items = [("experience", "Worked on a"), ("experience", "Worked on b"), ("projects", "worked on c"), ("projects", "Built d")]
        self.assertEqual(bullets.repeated_starts(items), ["worked"])
        self.assertEqual(bullets.repeated_starts(items[:2]), [])

    def test_review_of_a_whole_cv(self):
        cv = cv_builder.build({"contact": {"name": "A B"}, "skills": [{"items": "Python"}],
                               "projects": [{"title": "X", "points": ["Worked on a thing", "Built 3 APIs"]}]})
        r = bullets.review(cv)
        self.assertEqual(r["total"], 4)
        self.assertEqual([l["text"] for l in r["lines"]][-1], "Worked on a thing")


if __name__ == "__main__":
    unittest.main()
