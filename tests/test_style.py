import unittest

from core import style

ORIGINALS = {
    "projects.1": "Tested 12 web modules and logged 60+ defects",
    "projects.2": "Wrote test cases for login and payment pages",
    "skills.1": "Manual testing, SQL basics, Selenium basics",
    "projects.3": "Checked mobile screens on 5 phones",
}


class ClicheTests(unittest.TestCase):
    def test_finds_stock_phrases(self):
        found = style.find_cliches("Spearheaded testing and leveraged Selenium in a fast-paced team")
        self.assertIn("spearheaded", found)
        self.assertIn("leveraged", found)
        self.assertIn("fast-paced", found)

    def test_whole_words_only(self):
        self.assertEqual(style.find_cliches("Tested robustness of the API"), [])

    def test_users_own_words_are_allowed(self):
        own = style.cliches_in_user_text(["Self-motivated QA fresher", "Passionate about testing"])
        self.assertEqual(style.find_cliches("Passionate about testing", own), [])
        self.assertIn("leveraged", style.find_cliches("leveraged SQL", own))


class ProfileTests(unittest.TestCase):
    def test_profile_numbers(self):
        p = style.style_profile(list(ORIGINALS.values()))
        self.assertEqual(p["lines"], 4)
        self.assertEqual(p["ends_with_period"], 0.0)
        self.assertGreater(p["has_number"], 0.4)

    def test_empty_profile(self):
        self.assertEqual(style.style_profile([])["lines"], 0)


class LineChecks(unittest.TestCase):
    def setUp(self):
        self.profile = style.style_profile(list(ORIGINALS.values()))

    def test_long_line_and_full_stop_are_flagged(self):
        text = ("Tested a very large number of different web modules across several browsers and devices "
                "while also logging a great many defects for the whole team to review later.")
        flags = {w["flag"] for w in style.check_line(text, self.profile)}
        self.assertIn("long", flags)
        self.assertIn("full_stop", flags)

    def test_matching_style_has_no_warnings(self):
        self.assertEqual(style.check_line("Tested 8 web modules and logged 40 defects", self.profile), [])

    def test_small_profile_skips_shape_checks(self):
        tiny = style.style_profile(["Short line"])
        self.assertEqual(style.check_line("A much longer line than the only one the user wrote ever.", tiny), [])


class OutputChecks(unittest.TestCase):
    def test_kept_lines_are_never_flagged(self):
        lines = [{"text": "Tested 12 web modules and logged 60+ defects", "source_id": "projects.1", "change": "kept"}]
        self.assertEqual(style.check_output(lines, ORIGINALS), [])

    def test_cliche_and_heavy_rewrite_are_flagged(self):
        lines = [
            {"text": "Spearheaded quality assurance across modules", "source_id": "projects.1", "change": "reworded"},
            {"text": "Wrote test cases for login and payment screens", "source_id": "projects.2", "change": "reworded"},
        ]
        flags = [(r["index"], r["flag"]) for r in style.check_output(lines, ORIGINALS)]
        self.assertIn((0, "cliche"), flags)
        self.assertIn((0, "rewritten"), flags)
        self.assertNotIn((1, "rewritten"), flags)
        self.assertNotIn((1, "cliche"), flags)

    def test_new_lines_are_checked_for_cliches(self):
        lines = [{"text": "Leveraged Selenium for automation", "source_id": None, "change": "new"}]
        flags = [r["flag"] for r in style.check_output(lines, ORIGINALS)]
        self.assertIn("cliche", flags)

    def test_keep_ratio(self):
        self.assertEqual(style.keep_ratio("tested web modules", "tested web modules"), 1.0)
        self.assertLess(style.keep_ratio("tested web modules", "assured quality overall"), 0.5)


if __name__ == "__main__":
    unittest.main()
