"""Check whether a resume is easy for an Applicant Tracking System (ATS) to read.

What this checks, honestly: it reads the resume the way a simple text scanner
does (text in page order, then our own section parser) and looks for the
problems that really break scanners: spaced-out headings, the name not being
first, missing standard headings, missing contact details, icon characters.

What it does NOT do: it does not run any company's real ATS. Real systems differ.
Treat the score as "no obvious problems found", not as a guarantee.

Own code, standard library only.
"""

import re
from html.parser import HTMLParser

from . import render, resume_parser

ERROR, WARN, INFO = "error", "warn", "info"
_PENALTY = {ERROR: 20, WARN: 8, INFO: 3}

_BLOCK_TAGS = {"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "br", "section", "tr", "table"}
_SKIP_TAGS = {"style", "script", "head", "title"}

_SPACED = re.compile(r"^(?:[A-Za-z] ){3,}[A-Za-z]$")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d \-]{7,15}\d)(?!\d)")
_ICONS = re.compile("[←-⇿⌀-⏿☀-➿-\U0001f300-\U0001faff]")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_HEADING_WORDS = {"contact", "summary", "experience", "projects", "skills", "education", "certifications",
                  "profile", "objective", "achievements", "languages", "interests"}
MAX_WORDS = 900


class _TextInOrder(HTMLParser):
    """Visible text of an HTML page in document order, one entry per block."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = []
        self._buf = []
        self._skip = 0

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if text:
            self.lines.append(text)
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)

    def close(self):
        super().close()
        self._flush()


def html_text_lines(page_html):
    parser = _TextInOrder()
    parser.feed(page_html)
    parser.close()
    return parser.lines


FIXES = {
    "empty": "Add your CV text first (upload, paste, or build it from scratch).",
    "name_not_first": "Put only your full name on the very first line. Move email, phone and the job title to the lines below it (Your details box).",
    "spaced_headings": "Retype the headings as normal words. Some design tools add spaces between letters; use a simple template like Classic.",
    "no_sections": "Use standard headings: Education, Skills, Projects, Experience. Scanners look for these words.",
    "missing_experience": "Fresher: add a Projects section with 2 or 3 projects. Otherwise add your internships or jobs under Experience.",
    "missing_education": "Add an Education section with your degree, college and year.",
    "missing_skills": "Add a Skills section: tools and languages you can really use, separated by commas.",
    "no_email": "Add your email in Your details so it appears near the top.",
    "no_phone": "Add your phone number in Your details so it appears near the top.",
    "icons": "Remove emoji and icon symbols from your lines. Plain text is safest.",
    "no_dates": "Add years: for education the passing year, for jobs and internships the month and year.",
    "long_lines": "Split long lines into two shorter points of about 15-25 words.",
    "too_long": "Cut older or weaker lines. A fresher CV should fit on one page; two pages at most.",
    "photo": "If the job post does not ask for a photo, choose a template without a photo.",
    "two_columns": "Choose Classic, Modern or Compact (one column) if you are sending to a company website.",
}


def _finding(level, code, message):
    out = {"level": level, "code": code, "message": message}
    if code in FIXES:
        out["fix"] = FIXES[code]
    return out


def check_lines(lines):
    """Findings for a resume given as text lines in reading order."""
    findings = []
    lines = [ln.strip() for ln in lines if ln and ln.strip()]
    if not lines:
        return [_finding(ERROR, "empty", "No text found.")]

    first = lines[0]
    if "@" in first or len(first.split()) > 5 or first.lower().strip(":") in _HEADING_WORDS or _SPACED.match(first):
        findings.append(_finding(WARN, "name_not_first",
                                 "The first line should be your name. A scanner may read '%s' as your name." % first[:40]))

    spaced = [ln for ln in lines if _SPACED.match(ln)]
    if spaced:
        findings.append(_finding(ERROR, "spaced_headings",
                                 "Headings come out with spaces between letters (%s). Scanners will not recognise them." % spaced[0]))

    parsed = resume_parser.parse_resume("\n".join(lines))
    keys = {s["key"] for s in parsed["sections"]}
    if not keys:
        findings.append(_finding(ERROR, "no_sections",
                                 "No standard headings found (Experience, Education, Skills...)."))
    else:
        if not ({"experience", "projects"} & keys):
            findings.append(_finding(WARN, "missing_experience", "Add an Experience or Projects heading."))
        for key, label in (("education", "Education"), ("skills", "Skills")):
            if key not in keys:
                findings.append(_finding(WARN, "missing_" + key, "Add a %s heading." % label))

    top = " \n".join(lines[:14])
    if not _EMAIL.search(top):
        findings.append(_finding(ERROR, "no_email", "No email address near the top."))
    if not _PHONE.search(top):
        findings.append(_finding(WARN, "no_phone", "No phone number near the top."))

    joined = "\n".join(lines)
    if _ICONS.search(joined):
        findings.append(_finding(WARN, "icons", "Icons or special symbols can turn into junk characters in a scanner."))
    if not _YEAR.search(joined):
        findings.append(_finding(INFO, "no_dates", "No years found. Add dates to your experience and education."))
    if any(len(ln) > 250 for ln in lines):
        findings.append(_finding(INFO, "long_lines", "Some lines are very long. Shorter bullets are easier to read."))
    if len(joined.split()) > MAX_WORDS:
        findings.append(_finding(WARN, "too_long", "Probably more than two pages. Keep it to one or two."))
    return findings


def _score(findings):
    return max(0, 100 - sum(_PENALTY[f["level"]] for f in findings))


def check_text(text):
    """Check resume text we got from an uploaded file."""
    findings = check_lines(text.splitlines())
    return {"score": _score(findings), "findings": findings}


def check_resume(parsed, template=render.DEFAULT_TEMPLATE, photo=None):
    """Check how a saved resume reads when shown in a given template."""
    page = render.render_resume_html(parsed, template, photo)
    findings = check_lines(html_text_lines(page))
    if render.TEMPLATES[template]["photo"]:
        findings.append(_finding(INFO, "photo", "Scanners ignore photos, and some employers prefer CVs without one."))
    if template == "photo_sidebar":
        findings.append(_finding(INFO, "two_columns",
                                 "Two columns: some scanners read across both columns. Use a one-column template if unsure."))
    return {"score": _score(findings), "template": template, "findings": findings}
