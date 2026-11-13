"""Checks on the interface translations (Hindi, Marathi, Telugu). Run: python3 -m unittest tests.test_i18n"""
import json, os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "backend", "web")


def load():
    text = open(os.path.join(WEB, "i18n.js"), encoding="utf-8").read()
    start = text.index("window.I18N = ") + len("window.I18N = ")
    return json.loads(text[start:text.rindex(";")])


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.d = load()

    def test_three_languages(self):
        self.assertEqual(sorted(self.d), ["hi", "mr", "te"])

    def test_same_keys_everywhere(self):
        base = set(self.d["hi"])
        for lang in ("mr", "te"):
            self.assertEqual(base, set(self.d[lang]), lang)

    def test_no_empty_values(self):
        for lang, words in self.d.items():
            for key, val in words.items():
                self.assertTrue(val.strip(), (lang, key))

    def test_placeholders_match_english(self):
        for lang, words in self.d.items():
            for key, val in words.items():
                self.assertEqual(sorted(re.findall(r"\{\d\}", key)), sorted(re.findall(r"\{\d\}", val)), (lang, key))

    def test_right_script_used(self):
        ranges = {"hi": "ऀ-ॿ", "mr": "ऀ-ॿ", "te": "ఀ-౿"}
        for lang, words in self.d.items():
            hits = sum(1 for v in words.values() if re.search("[" + ranges[lang] + "]", v))
            self.assertGreater(hits / len(words), 0.95, lang)

    def test_keys_are_trimmed(self):
        for key in self.d["hi"]:
            self.assertEqual(key, key.strip())

    def test_file_is_served_and_loaded(self):
        views = open(os.path.join(ROOT, "backend", "packs", "web_views.py"), encoding="utf-8").read()
        self.assertIn('"i18n.js"', views)
        self.assertIn("/app/i18n.js", open(os.path.join(WEB, "index.html"), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
