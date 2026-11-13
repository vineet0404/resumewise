"""Edit a parsed resume: contact details, add, change and remove lines.

Every function takes the parsed resume (the dict from resume_parser) and returns
a NEW dict; the input is never changed. Problems raise EditError with a message
that is safe to show to the user.

Line ids are never reused. `parsed["next"]` remembers the last number given out
per section, so an id that was deleted cannot come back with different text and
silently re-attach to an old tailored resume.
"""

import copy
import re

MAX_LINE_CHARS = 400
MAX_ITEMS_PER_SECTION = 50
MAX_SECTIONS = 12
MAX_ITEMS_TOTAL = 300
MAX_LINKS = 5

SECTION_TITLES = {
    "summary": "SUMMARY",
    "experience": "EXPERIENCE",
    "projects": "PROJECTS",
    "education": "EDUCATION",
    "skills": "SKILLS",
    "certifications": "CERTIFICATIONS",
    "achievements": "ACHIEVEMENTS",
    "languages": "LANGUAGES",
    "interests": "INTERESTS",
    "personal": "PERSONAL DETAILS",
}

# The last part (com, org, COM, Com) stops at a case change, so "a@b.orgInstitute" gives "a@b.org".
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.(?:[a-z]{2,24}(?![a-z])|[A-Z]{2,24}(?![A-Z])|[A-Z][a-z]{1,23}(?![a-z]))")
_PHONE_FIND = re.compile(r"(?<!\d)(?:\+?91[\s\-]?|0)?[6-9]\d{4}[\s\-]?\d{5}(?!\d)")
_URL_FIND = re.compile(r"(?:https?://|www\.)[^\s)\]>,;]+", re.IGNORECASE)
_SOCIAL_FIND = re.compile(
    r"(?<![A-Za-z0-9@.])(?:[a-z]{2,3}\.)?(?:linkedin|github|gitlab|behance|medium|kaggle)\.com/[^\s|,;)\]>]+"
    r"|(?<![\w/@.])in/[A-Za-z0-9_%-]{3,}",
    re.IGNORECASE,
)
MAX_NAME = 80
MAX_LOCATION = 80
_PHONE_OK = re.compile(r"^\+?[0-9][0-9 \-]{6,18}[0-9]$")
_LINK_OK = re.compile(r"^(https?://)?[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(/[^\s]*)?$")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ID = re.compile(r"^([a-z]+)\.(\d+)$")


class EditError(ValueError):
    """The change is not allowed. The message is safe to show to the user."""


def _clean_line(text):
    if not isinstance(text, str):
        raise EditError("text must be a string")
    text = _CONTROL.sub("", text).strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        raise EditError("text cannot be empty")
    if len(text) > MAX_LINE_CHARS:
        raise EditError("a line can be at most %d characters" % MAX_LINE_CHARS)
    return text


def _item_count(parsed):
    return sum(len(s["items"]) for s in parsed["sections"])


_LETTERHEAD = re.compile(r"institute|address|campus|phone nos|e-?mail id|placement|\bT&P\b", re.I)


def with_contact(parsed):
    """Return a copy that has a `contact` block, guessed from the header if missing."""
    out = copy.deepcopy(parsed)
    if "contact" in out:
        out["contact"].setdefault("name", guess_name(out.get("header", [])))
        return out
    lines = [h for h in out.get("header", [])]
    name = guess_name(lines)
    if name in lines:
        at = lines.index(name)
        # Lines above the name that read like a college letterhead are not the person's contact details.
        lines = [ln for i, ln in enumerate(lines) if not (i < at and _LETTERHEAD.search(ln))]
    header = " \n".join(lines)
    email = _EMAIL.search(header)
    phone = _PHONE_FIND.search(header)
    links = []
    for pattern in (_URL_FIND, _SOCIAL_FIND):
        for m in pattern.finditer(header):
            link = m.group(0).rstrip(".")
            if not any(link in other or other in link for other in links):
                links.append(link)
    out["contact"] = {
        "name": guess_name(out.get("header", [])),
        "email": email.group(0) if email else "",
        "phone": phone.group(0).strip() if phone else "",
        "links": links[:MAX_LINKS],
        "location": _guess_location(lines),
    }
    return out


_NOT_A_NAME = {"institute", "address", "phone", "email", "mail", "batch", "university", "college", "resume",
                "curriculum", "vitae", "objective", "summary", "profile", "contact", "school", "limited",
                "ltd", "pvt", "department", "mca", "mba", "btech", "campus", "nos", "id"}
_NAME_WORD = re.compile(r"[A-Za-z][A-Za-z.'\-]*")


def _plausible_name(line):
    if len(line) > 40 or re.search(r"[\d@:|]", line):
        return False
    return not any(w.lower().strip(".,") in _NOT_A_NAME for w in line.split())


def guess_name(header_lines):
    """The line that looks like a person's name (2 to 4 plain words), else the first line."""
    lines = [h.strip() for h in header_lines if h and h.strip()]
    if lines and _plausible_name(lines[0]):
        return lines[0]  # the first line is normally the name; only look further when it is not
    for line in lines[:12]:
        words = line.split()
        if not 2 <= len(words) <= 4 or len(line) > 40:
            continue
        if not all(_NAME_WORD.fullmatch(w) for w in words):
            continue
        if any(w.lower().strip(".") in _NOT_A_NAME for w in words):
            continue
        return line
    return lines[0] if lines else ""


def _guess_location(header_lines):
    """The first short piece of the header that is not a name, email, phone or link."""
    name = guess_name(header_lines)
    for line in header_lines:
        if line.strip() == name:
            continue  # the name
        pieces = re.split(r"\s*[|\u00b7\u2022]\s*", line)
        for piece in pieces:
            piece = re.sub(r"^[^\w]+", "", piece.strip())  # icons such as a house or phone symbol in front
            if not piece or len(piece) > MAX_LOCATION:
                continue
            if _EMAIL.search(piece) or _PHONE_FIND.search(piece) or _URL_FIND.search(piece) or _SOCIAL_FIND.search(piece):
                continue
            if re.search(r"engineer|developer|tester|analyst|manager|intern|fresher", piece, re.I):
                continue
            if re.fullmatch(r"[A-Za-z0-9 .,\-/#]+", piece) and "," in piece:
                return piece
            if len(pieces) > 1 and re.fullmatch(r"[A-Za-z]+(?: [A-Za-z]+){0,2}", piece):
                return piece  # "email | phone | Bengaluru": a lone city between separators
    return ""


def set_contact(parsed, email=None, phone=None, links=None, location=None, name=None):
    """Change any of name, email, phone, links, location. A field left as None is kept. "" clears it."""
    out = with_contact(parsed)
    contact = out["contact"]
    if name is not None:
        if not isinstance(name, str):
            raise EditError("name must be a string")
        name = re.sub(r"\s+", " ", _CONTROL.sub("", name)).strip()
        if len(name) > MAX_NAME:
            raise EditError("name can be at most %d characters" % MAX_NAME)
        contact["name"] = name
    if email is not None:
        if not isinstance(email, str):
            raise EditError("email must be a string")
        email = email.strip()
        if email and (len(email) > 254 or not re.fullmatch(_EMAIL, email)):
            raise EditError("enter a valid email")
        contact["email"] = email
    if phone is not None:
        if not isinstance(phone, str):
            raise EditError("phone must be a string")
        phone = phone.strip()
        if phone and not _PHONE_OK.match(phone):
            raise EditError("enter a valid phone number")
        contact["phone"] = phone
    if location is not None:
        if not isinstance(location, str):
            raise EditError("location must be a string")
        location = re.sub(r"\s+", " ", _CONTROL.sub("", location)).strip()
        if len(location) > MAX_LOCATION:
            raise EditError("location can be at most %d characters" % MAX_LOCATION)
        contact["location"] = location
    if links is not None:
        if not isinstance(links, list) or len(links) > MAX_LINKS:
            raise EditError("links must be a list of at most %d items" % MAX_LINKS)
        cleaned = []
        for link in links:
            if not isinstance(link, str):
                raise EditError("each link must be a string")
            link = link.strip()
            if not link:
                continue
            if len(link) > 200 or not _LINK_OK.match(link) or link.lower().startswith(("javascript:", "data:")):
                raise EditError("enter valid links (for example linkedin.com/in/yourname)")
            cleaned.append(link)
        contact["links"] = cleaned
    return out


def _find_section(parsed, key):
    for section in parsed["sections"]:
        if section["key"] == key:
            return section
    return None


def _next_id(parsed, key):
    section = _find_section(parsed, key)
    used = 0
    if section:
        for item in section["items"]:
            m = _ID.match(item["id"])
            if m:
                used = max(used, int(m.group(2)))
    counters = parsed.setdefault("next", {})
    number = max(used, counters.get(key, 0)) + 1
    counters[key] = number
    return "%s.%d" % (key, number)


def add_item(parsed, section_key, text):
    """Add a line at the end of a section. The section is created if it is missing."""
    if section_key not in SECTION_TITLES:
        raise EditError("unknown section; use one of: " + ", ".join(sorted(SECTION_TITLES)))
    text = _clean_line(text)
    out = copy.deepcopy(parsed)
    if _item_count(out) >= MAX_ITEMS_TOTAL:
        raise EditError("the CV has too many lines")
    section = _find_section(out, section_key)
    if section is None:
        if len(out["sections"]) >= MAX_SECTIONS:
            raise EditError("the CV has too many sections")
        section = {"key": section_key, "title": SECTION_TITLES[section_key], "items": []}
        out["sections"].append(section)
    if len(section["items"]) >= MAX_ITEMS_PER_SECTION:
        raise EditError("this section is full")
    item_id = _next_id(out, section_key)
    section["items"].append({"id": item_id, "text": text})
    return out, item_id


def _locate(parsed, item_id):
    for section in parsed["sections"]:
        for index, item in enumerate(section["items"]):
            if item["id"] == item_id:
                return section, index
    raise EditError("that line does not exist")


def edit_item(parsed, item_id, text):
    text = _clean_line(text)
    out = copy.deepcopy(parsed)
    section, index = _locate(out, item_id)
    section["items"][index]["text"] = text
    return out


def remove_item(parsed, item_id):
    out = copy.deepcopy(parsed)
    section, index = _locate(out, item_id)
    # Remember the number so this id is never handed out again.
    m = _ID.match(item_id)
    if m:
        counters = out.setdefault("next", {})
        counters[m.group(1)] = max(counters.get(m.group(1), 0), int(m.group(2)))
    del section["items"][index]
    if not section["items"]:
        out["sections"].remove(section)
    return out


def name_and_role(parsed):
    """(name, role) for the top of a resume. The name is the user's edited or guessed name."""
    header = [h.strip() for h in parsed.get("header", []) if h and h.strip()]
    name = (parsed.get("contact") or {}).get("name") or guess_name(header) or "Your Name"
    role = ""
    after = header[header.index(name) + 1:] if name in header else header[1:]
    for line in after:
        if line.strip().lower() == name.strip().lower():
            continue
        if "@" in line or "http" in line.lower() or ":" in line or "|" in line or re.search(r"\d", line):
            continue
        if len(line) <= 60:
            role = line
            break
    return name[:80], role


def contact_line(parsed):
    """One plain line: location | email | phone | links."""
    c = with_contact(parsed)["contact"]
    return " | ".join(x for x in [c.get("location"), c.get("email"), c.get("phone")] + list(c.get("links", [])) if x)
