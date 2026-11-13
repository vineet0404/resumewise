"""Split plain resume text into sections and numbered items.

Every item gets a stable id such as "projects.2". Later steps (tailoring and
verification) use those ids to prove that every output line comes from the
user's own resume.

This is a rule-based first version. It works on text already extracted from a
PDF or DOCX and is meant to be reviewed and corrected by the user.
"""

import re

# Heading text (lower case) -> section key.
_HEADINGS = {
    "summary": "summary",
    "professional summary": "summary",
    "profile": "summary",
    "objective": "summary",
    "career objective": "summary",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "employment": "experience",
    "internship": "experience",
    "internships": "experience",
    "projects": "projects",
    "academic projects": "projects",
    "education": "education",
    "academics": "education",
    "skills": "skills",
    "technical skills": "skills",
    "key skills": "skills",
    "certifications": "certifications",
    "certificates": "certifications",
    "achievements": "achievements",
    "awards": "achievements",
    "languages": "languages",
    "interests": "interests",
    "projects undertaken": "projects",
    "personal projects": "projects",
    "major projects": "projects",
    "key projects": "projects",
    "project work": "projects",
    "academic qualification": "education",
    "academic qualifications": "education",
    "educational qualification": "education",
    "educational qualifications": "education",
    "qualification": "education",
    "qualifications": "education",
    "education and training": "education",
    "skills and abilities": "skills",
    "it skills": "skills",
    "professional skills": "skills",
    "core competencies": "skills",
    "technical proficiency": "skills",
    "career summary": "summary",
    "professional profile": "summary",
    "about me": "personal",
    "personal information": "personal",
    "declaration": "personal",
    "certification program": "certifications",
    "certification programs": "certifications",
    "certification programme": "certifications",
    "cocurricular and extracurricular activities": "achievements",
    "co curricular and extra curricular activities": "achievements",
    "languages known": "languages",
    "hobbies": "interests",
    "hobbies and interests": "interests",
    "extracurricular activities": "achievements",
    "extra curricular activities": "achievements",
    "awards and achievements": "achievements",
    "training and certifications": "certifications",
    "courses": "certifications",
    "contact": "contact",
    "contact details": "contact",
    "personal details": "personal",
    "top skills": "skills",
    "skill set": "skills",
    "technical skill set": "skills",
    "work history": "experience",
    "employment history": "experience",
    "professional background": "experience",
    "volunteering": "achievements",
    "publications": "achievements",
    "honors and awards": "achievements",
    "interests and hobbies": "interests",
}
_NOSPACE = {k.replace(" ", ""): v for k, v in _HEADINGS.items()}

_BULLET = re.compile(r"^\s*(?:[-*•●▪‣►▶◦○■□✓✔➢➤➔→–—]|\d{1,2}[.)])\s+")


def _heading_key(line):
    cleaned = re.sub(r"[^a-z ]", "", line.lower()).strip()
    if not cleaned or len(line.strip()) > 60:
        return None
    return _HEADINGS.get(cleaned) or _NOSPACE.get(cleaned.replace(" ", ""))


_NAME_WORD = re.compile(r"^[A-Z][A-Za-z'-]*\.?$")
_SIDEBAR_KEYS = ("languages", "interests", "skills")


def _name_like(line):
    words = line.split()
    return 2 <= len(words) <= 4 and len(line) <= 32 and all(_NAME_WORD.match(w) for w in words) and not _heading_key(line)


def _rescue_name(header, sections):
    """Two-column CVs (LinkedIn export, Canva) print the sidebar first, so the person's name ends up
    as the last lines of a sidebar section such as Languages. When the header has no name, move
    that tail (name, job title, city) up into the header."""
    if any(_name_like(ln) for ln in header[:2]):
        return
    for sec in sections:
        if not sec["key"].rstrip("0123456789") in _SIDEBAR_KEYS:
            continue
        items = sec["items"]
        for i in range(1, min(len(items), 12)):
            text = items[i]["text"]
            if len(items) - i <= 4 and _name_like(text) and (sec["key"].rstrip("0123456789") != "skills" or text.isupper()):
                header[:0] = [it["text"] for it in items[i:]]
                del items[i:]
                return


def parse_resume(text):
    """Return {"header": [str], "sections": [{"key", "title", "items": [{"id", "text"}]}]}."""
    header = []
    sections = []
    current = None
    counts = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        key = _heading_key(line)
        if key == "contact":
            current = None  # contact lines belong to the header, not to a section
            continue
        if key:
            current = {"key": key, "title": line.rstrip(":").strip(), "items": []}
            counts[key] = counts.get(key, 0) + 1
            if counts[key] > 1:
                current["key"] = "%s%d" % (key, counts[key])
            sections.append(current)
            continue
        if current is None:
            header.append(line)
            continue
        item_text = _BULLET.sub("", line).strip()
        if not item_text:
            continue
        # "Databases:" on its own line, then "MySql" and "SQL" on the next lines: one item.
        open_label = current["items"][-1] if current["items"] and current.get("_label") else None
        if open_label is not None and not _BULLET.match(raw) and not item_text.endswith(":") and len(item_text) <= 60:
            joiner = " " if open_label["text"].endswith(":") else ", "
            open_label["text"] += joiner + item_text
            continue
        current["_label"] = False
        # A wrapped line (no bullet, previous item had no sentence end) joins the previous item.
        previous = current["items"][-1] if current["items"] else None
        if (
            previous is not None
            and not _BULLET.match(raw)
            and raw[:1].islower()
            and not previous["text"].rstrip().endswith((".", ";", ":"))
        ):
            previous["text"] += " " + item_text
            continue
        current["items"].append(
            {"id": "%s.%d" % (current["key"], len(current["items"]) + 1), "text": item_text}
        )
        if item_text.endswith(":") and len(item_text) <= 40 and not _BULLET.match(raw):
            current["_label"] = True
    for section in sections:
        section.pop("_label", None)
    _rescue_name(header, sections)
    return {"header": header, "sections": sections}


def all_items(parsed):
    """Flat {id: text} of every item in the parsed resume."""
    return {item["id"]: item["text"] for section in parsed["sections"] for item in section["items"]}
