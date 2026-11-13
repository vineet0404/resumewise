"""Build a parsed resume from form answers ("Build from scratch" wizard).

Nothing is invented here: every line in the result is text the person typed, only
joined with " | ". The result has the same shape as `resume_parser.parse_resume`
(header, sections with items and ids) plus a `contact` block, so templates, ATS
check, editing, history and tailoring work on it exactly as on an uploaded CV.
"""

from . import profile_edit
from .profile_edit import EditError

MAX_ENTRIES = {"education": 6, "projects": 8, "experience": 8}
MAX_POINTS = 8
MAX_SKILL_GROUPS = 10
MAX_PLAIN = 15


def _text(value, label):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise EditError("%s must be text" % label)
    return value.strip()


def _join(*parts):
    return " | ".join(p for p in parts if p)


def _entries(data, key):
    rows = data.get(key) or []
    if not isinstance(rows, list):
        raise EditError("%s must be a list" % key)
    if len(rows) > MAX_ENTRIES[key]:
        raise EditError("too many %s entries (limit %d)" % (key, MAX_ENTRIES[key]))
    for row in rows:
        if not isinstance(row, dict):
            raise EditError("each %s entry must be an object" % key)
    return rows


def _points(row):
    pts = row.get("points") or []
    if isinstance(pts, str):
        pts = pts.splitlines()
    if not isinstance(pts, list):
        raise EditError("points must be a list")
    pts = [_text(p, "a point") for p in pts]
    pts = [p for p in pts if p]
    if len(pts) > MAX_POINTS:
        raise EditError("too many points in one entry (limit %d)" % MAX_POINTS)
    return pts


def _plain_list(data, key):
    rows = data.get(key) or []
    if isinstance(rows, str):
        rows = rows.splitlines()
    if not isinstance(rows, list):
        raise EditError("%s must be a list" % key)
    rows = [_text(r, key) for r in rows]
    rows = [r for r in rows if r]
    if len(rows) > MAX_PLAIN:
        raise EditError("too many lines in %s (limit %d)" % (key, MAX_PLAIN))
    return rows


def lines_for(data):
    """[(section key, line text)] in resume order, from the wizard answers."""
    if not isinstance(data, dict):
        raise EditError("send the answers as an object")
    out = []
    summary = _text(data.get("summary"), "summary")
    if summary:
        out.append(("summary", summary))
    for row in _entries(data, "experience"):
        head = _join(_text(row.get("role"), "role"), _text(row.get("company"), "company"), _text(row.get("dates"), "dates"))
        pts = _points(row)
        if head:
            out.append(("experience", head))
        elif pts:
            raise EditError("add a role or company for each experience entry")
        out += [("experience", p) for p in pts]
    for row in _entries(data, "projects"):
        head = _join(_text(row.get("title"), "project title"), _text(row.get("tech"), "technologies"))
        pts = _points(row)
        if head:
            out.append(("projects", head))
        elif pts:
            raise EditError("add a title for each project")
        out += [("projects", p) for p in pts]
    skills = data.get("skills") or []
    if isinstance(skills, str):
        skills = [{"items": skills}]
    if not isinstance(skills, list):
        raise EditError("skills must be a list")
    if len(skills) > MAX_SKILL_GROUPS:
        raise EditError("too many skill groups (limit %d)" % MAX_SKILL_GROUPS)
    for row in skills:
        if isinstance(row, str):
            row = {"items": row}
        if not isinstance(row, dict):
            raise EditError("each skill group must be an object")
        items = _text(row.get("items"), "skills")
        group = _text(row.get("group"), "skill group")
        if items:
            out.append(("skills", "%s: %s" % (group, items) if group else items))
    for row in _entries(data, "education"):
        line = _join(_text(row.get("degree"), "degree"), _text(row.get("school"), "school"),
                     _text(row.get("years"), "years"), _text(row.get("score"), "score"))
        if line:
            out.append(("education", line))
    for key in ("certifications", "achievements", "languages"):
        out += [(key, r) for r in _plain_list(data, key)]
    return out


def build(data):
    """Return the parsed resume. Raises EditError with a message that is safe to show."""
    if not isinstance(data, dict):
        raise EditError("send the answers as an object")
    contact = data.get("contact")
    if not isinstance(contact, dict):
        raise EditError("add your name and contact details")
    name = _text(contact.get("name"), "name")
    if not name:
        raise EditError("your name is required")
    lines = lines_for(data)
    if not lines:
        raise EditError("add at least one line (education, skills, a project...) before building")
    role = _text(data.get("role"), "job title")
    header = [name] + ([role] if role else [])
    parsed = {"header": header, "sections": []}
    for key, text in lines:
        parsed, _ = profile_edit.add_item(parsed, key, text)
    links = contact.get("links") or []
    if isinstance(links, str):
        links = [x.strip() for x in links.split(",")]
    return profile_edit.set_contact(
        parsed, name=name, email=_text(contact.get("email"), "email"), phone=_text(contact.get("phone"), "phone"),
        location=_text(contact.get("location"), "location"), links=links)
