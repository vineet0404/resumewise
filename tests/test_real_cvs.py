"""Layouts seen in real CVs: Canva (letter-spaced headings, sidebar first), LinkedIn export, bullets, footers."""
import unittest

from core import extract, profile_edit, resume_parser

CANVA = """C O N TA C T
✆  +91 77000 33445
✉  rohan.mehta@outlook.com
⌂ Pune, India
in/rohanmehta
S K I L L S
JavaScript React Node.js
Figma
L A N G U A G E S
English
Marathi
ROHAN MEHTA
F R O N T E N D  D E V E L O P E R
P R O F I L E
Creative developer who loves clean interfaces.
W O R K  E X P E R I E N C E
Frontend Intern — Pixel Works
Built 14 reusable React components.
E D U C AT I O N
B.Sc. Computer Science, Pune University, 2021 – 2024"""

LINKEDIN = """Contact
+91 98200 11122
priya.nair@gmail.com
www.linkedin.com/in/priyanair
(LinkedIn)
Top Skills
Python
Django
Languages
English (Full Professional)
Hindi (Native)
Priya Nair
Backend Developer at Zeta Labs
Mumbai, Maharashtra, India
Summary
Backend developer with 3 years of experience.
Experience
Zeta Labs
Backend Developer"""


def keys(parsed):
    return [s["key"] for s in parsed["sections"]]


class SpacedHeadings(unittest.TestCase):
    def test_letters_are_joined(self):
        out = extract._join_spaced_letters("E D U C AT I O N\nW O R K  E X P E R I E N C E\nF R O N T E N D  D E V E L O P E R")
        self.assertEqual(out.split("\n"), ["EDUCATION", "WORK EXPERIENCE", "FRONTEND DEVELOPER"])

    def test_normal_short_lines_are_left_alone(self):
        for line in ("C R Go", "Skills: C, R, Go", "I am a QA", "Java C# R SQL Go"):
            self.assertEqual(extract._join_spaced_letters(line), line)

    def test_parser_also_matches_a_spaced_heading(self):
        parsed = resume_parser.parse_resume("Name Here\nE D U C AT I O N\nB.Sc. Pune University 2024")
        self.assertEqual(keys(parsed), ["education"])


class SidebarFirstLayouts(unittest.TestCase):
    def test_canva_name_moves_out_of_languages(self):
        parsed = resume_parser.parse_resume(extract._join_spaced_letters(CANVA))
        self.assertEqual(keys(parsed), ["skills", "languages", "summary", "experience", "education"])
        self.assertEqual([i["text"] for i in parsed["sections"][1]["items"]], ["English", "Marathi"])
        self.assertEqual(parsed["header"][:2], ["ROHAN MEHTA", "FRONTEND DEVELOPER"])
        contact = profile_edit.with_contact(parsed)["contact"]
        self.assertEqual((contact["name"], contact["email"], contact["location"]), ("ROHAN MEHTA", "rohan.mehta@outlook.com", "Pune, India"))
        self.assertEqual(contact["links"], ["in/rohanmehta"])

    def test_linkedin_name_moves_out_of_languages(self):
        parsed = resume_parser.parse_resume(LINKEDIN)
        self.assertEqual(keys(parsed), ["skills", "languages", "summary", "experience"])
        self.assertEqual(parsed["header"][:3], ["Priya Nair", "Backend Developer at Zeta Labs", "Mumbai, Maharashtra, India"])
        self.assertEqual(len(parsed["sections"][1]["items"]), 2)
        self.assertEqual(profile_edit.with_contact(parsed)["contact"]["name"], "Priya Nair")

    def test_a_real_language_list_is_not_touched(self):
        parsed = resume_parser.parse_resume("Jane Doe\njane@x.com\nLanguages\nEnglish\nHindi\nMarathi\nExperience\nWorked at Acme.")
        self.assertEqual([i["text"] for i in parsed["sections"][0]["items"]], ["English", "Hindi", "Marathi"])

    def test_a_cv_with_a_name_in_the_header_is_untouched(self):
        parsed = resume_parser.parse_resume("Jane Doe\nSkills\nMachine Learning\nData Science\nExperience\nWorked at Acme.")
        self.assertEqual([i["text"] for i in parsed["sections"][0]["items"]], ["Machine Learning", "Data Science"])


class SmallThings(unittest.TestCase):
    def test_arrow_and_other_bullets_are_stripped(self):
        parsed = resume_parser.parse_resume("A B\nExperience\n► Cut defects by 45%\n■ Wrote tests\n✓ Led a team")
        self.assertEqual([i["text"] for i in parsed["sections"][0]["items"]], ["Cut defects by 45%", "Wrote tests", "Led a team"])

    def test_page_footers_are_dropped_but_numbers_in_text_stay(self):
        out = extract._drop_page_noise("Experience\nPage 1 of 2\nPage 2\n1/2\nWorked 2/3 of the year\nScored 9 of 10")
        self.assertEqual(out.split("\n"), ["Experience", "Worked 2/3 of the year", "Scored 9 of 10"])

    def test_lone_city_between_separators(self):
        c = profile_edit.with_contact({"header": ["SNEHA RAO", "sneha@proton.me · +91 90000 12345 · Bengaluru · github.com/snehar"], "sections": []})["contact"]
        self.assertEqual((c["location"], c["links"]), ("Bengaluru", ["github.com/snehar"]))


if __name__ == "__main__":
    unittest.main()
