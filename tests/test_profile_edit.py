import copy
import unittest

from core import profile_edit as pe
from core import resume_parser

RESUME = """Aarti Sharma
aarti@example.com | +91 98765 43210 | linkedin.com/in/aarti

PROJECTS
- Tested 12 web modules
- Wrote test cases
"""


def base():
    return resume_parser.parse_resume(RESUME)


class ContactTests(unittest.TestCase):
    def test_contact_is_guessed_from_header(self):
        c = pe.with_contact(base())["contact"]
        self.assertEqual(c["email"], "aarti@example.com")
        self.assertIn("98765", c["phone"])

    def test_set_contact_changes_only_given_fields(self):
        out = pe.set_contact(base(), phone="+91 99999 11111")
        self.assertEqual(out["contact"]["phone"], "+91 99999 11111")
        self.assertEqual(out["contact"]["email"], "aarti@example.com")

    def test_clearing_and_links(self):
        out = pe.set_contact(base(), email="", links=["github.com/aarti", "https://linkedin.com/in/aarti"])
        self.assertEqual(out["contact"]["email"], "")
        self.assertEqual(len(out["contact"]["links"]), 2)

    def test_bad_values_are_refused(self):
        for kwargs in ({"email": "nope"}, {"phone": "abc"}, {"links": ["javascript:alert(1)"]},
                       {"links": ["a.com"] * 6}, {"links": "x"}, {"email": 5}):
            with self.assertRaises(pe.EditError):
                pe.set_contact(base(), **kwargs)

    def test_input_is_not_changed(self):
        original = base()
        snapshot = copy.deepcopy(original)
        pe.set_contact(original, email="new@example.com")
        self.assertEqual(original, snapshot)


class LocationAndLinkTests(unittest.TestCase):
    TEXT = ("Aarti Sharma\nJunior QA Engineer\n"
            "Mumbai, Maharashtra | aarti@example.com | +91 98765 43210 | linkedin.com/in/aarti-sharma | github.com/aarti-sharma\n\n"
            "PROJECTS\n- Tested modules\n")

    def test_bare_links_and_location_are_found(self):
        c = pe.with_contact(resume_parser.parse_resume(self.TEXT))["contact"]
        self.assertEqual(c["location"], "Mumbai, Maharashtra")
        self.assertEqual(c["email"], "aarti@example.com")
        self.assertEqual(sorted(c["links"]), ["github.com/aarti-sharma", "linkedin.com/in/aarti-sharma"])

    def test_https_link_is_not_listed_twice(self):
        text = "Aarti Sharma\nhttps://linkedin.com/in/aarti | linkedin.com/in/aarti\n\nPROJECTS\n- x\n"
        links = pe.with_contact(resume_parser.parse_resume(text))["contact"]["links"]
        self.assertEqual(len(links), 1)

    def test_role_line_is_not_taken_as_location(self):
        c = pe.with_contact(resume_parser.parse_resume(self.TEXT))["contact"]
        self.assertNotIn("Engineer", c["location"])

    def test_set_location(self):
        out = pe.set_contact(base(), location="  Pune,   Maharashtra ")
        self.assertEqual(out["contact"]["location"], "Pune, Maharashtra")
        with self.assertRaises(pe.EditError):
            pe.set_contact(base(), location="x" * 81)
        with self.assertRaises(pe.EditError):
            pe.set_contact(base(), location=5)


class ItemTests(unittest.TestCase):
    def test_add_to_existing_and_new_section(self):
        out, new_id = pe.add_item(base(), "projects", "  Built a login   checker ")
        self.assertEqual(new_id, "projects.3")
        self.assertEqual(out["sections"][0]["items"][-1]["text"], "Built a login checker")
        out, exp_id = pe.add_item(out, "experience", "QA Intern at Diebold, 2025")
        self.assertEqual(exp_id, "experience.1")
        self.assertEqual(out["sections"][-1]["title"], "EXPERIENCE")

    def test_ids_are_never_reused_after_delete(self):
        out, first = pe.add_item(base(), "projects", "Third")
        out = pe.remove_item(out, first)
        out, second = pe.add_item(out, "projects", "Fourth")
        self.assertNotEqual(first, second)
        out = pe.remove_item(out, "projects.1")
        out = pe.remove_item(out, "projects.2")
        out = pe.remove_item(out, second)
        out, third = pe.add_item(out, "projects", "Fresh")
        self.assertNotIn(third, {first, second, "projects.1", "projects.2"})

    def test_edit_keeps_id(self):
        out = pe.edit_item(base(), "projects.2", "Wrote 40 test cases")
        item = [i for i in out["sections"][0]["items"] if i["id"] == "projects.2"][0]
        self.assertEqual(item["text"], "Wrote 40 test cases")

    def test_empty_section_is_dropped(self):
        out = pe.remove_item(pe.remove_item(base(), "projects.1"), "projects.2")
        self.assertEqual(out["sections"], [])

    def test_validation(self):
        with self.assertRaises(pe.EditError):
            pe.add_item(base(), "hobbies", "x")
        with self.assertRaises(pe.EditError):
            pe.add_item(base(), "projects", "   ")
        with self.assertRaises(pe.EditError):
            pe.add_item(base(), "projects", "x" * 401)
        with self.assertRaises(pe.EditError):
            pe.add_item(base(), "projects", 5)
        with self.assertRaises(pe.EditError):
            pe.edit_item(base(), "projects.99", "x")
        with self.assertRaises(pe.EditError):
            pe.remove_item(base(), "nope.1")

    def test_control_characters_are_removed(self):
        out, new_id = pe.add_item(base(), "skills", "Python\x00\x07 and SQL")
        self.assertEqual(out["sections"][-1]["items"][0]["text"], "Python and SQL")

    def test_section_limit(self):
        parsed = base()
        for i in range(pe.MAX_ITEMS_PER_SECTION - 2):
            parsed, _ = pe.add_item(parsed, "projects", "line %d" % i)
        with self.assertRaises(pe.EditError):
            pe.add_item(parsed, "projects", "one too many")


if __name__ == "__main__":
    unittest.main()
