"""LinkedIn profile help built only from the CV: headline options, an About draft, skills to add, things to feature,
and a checklist. No AI and nothing invented: every fact comes from a CV line or from the target role the person types.
The person edits everything before pasting it into LinkedIn.
"""

import re

from . import profile_edit

HEADLINE_LIMIT = 220  # LinkedIn's own limit
MAX_SKILLS = 20
_LABEL = re.compile(r"^[A-Za-z /&+.-]{2,30}:\s*")
_URL = re.compile(r"(?:https?://|www\.)\S+|(?:github|gitlab|linkedin)\.com/\S+", re.I)


def _items(parsed, key):
    return [i["text"] for s in parsed.get("sections", []) if s["key"] == key for i in s["items"]]


def _nice(line):
    return line.replace(" | ", ", ").strip().rstrip(".")


def skills(parsed):
    """The skill words listed in the Skills section, in the person's order, without group labels or duplicates."""
    out, seen = [], set()
    for line in _items(parsed, "skills"):
        for part in re.split(r"[|;,]", _LABEL.sub("", line)):
            part = _LABEL.sub("", part).strip(" .")
            if 1 < len(part) <= 40 and part.lower() not in seen:
                seen.add(part.lower())
                out.append(part)
    return out


def _degree(parsed):
    """First part of the first education line, for example 'MCA'. Empty when there is none."""
    edu = _items(parsed, "education")
    if not edu:
        return ""
    first = re.split(r"\s\|\s|,", edu[0])[0].strip()
    return first if 1 < len(first) <= 60 else ""


def _clip(parts, sep=" | "):
    """Join parts, dropping the last ones until the text fits LinkedIn's headline limit."""
    parts = [p for p in parts if p]
    while len(sep.join(parts)) > HEADLINE_LIMIT and len(parts) > 1:
        parts.pop()
    return sep.join(parts)[:HEADLINE_LIMIT]


def headlines(parsed, target=""):
    sk, degree = skills(parsed), _degree(parsed)
    contact = (profile_edit.with_contact(parsed).get("contact") or {})
    place = (contact.get("location") or "").strip()
    target = target.strip()
    out = []
    if target:
        out.append({"label": "Role first (best for recruiter search)", "text": _clip([target] + sk[:4])})
        out.append({"label": "Open to this role", "text": _clip([degree, "Open to %s roles" % target] + sk[:3])})
    if sk:
        out.append({"label": "Skills first", "text": _clip(sk[:5] + [degree])})
    if degree and sk:
        out.append({"label": "Education and strengths", "text": _clip([degree, " and ".join(sk[:2])] + ([place] if place else []))})
    seen, unique = set(), []
    for o in out:
        if o["text"] and o["text"] not in seen:
            seen.add(o["text"])
            unique.append(o)
    return unique


def about(parsed, target=""):
    """A short first-person About text. Each line is a CV line or a plain sentence made from CV facts."""
    paras = []
    edu = _items(parsed, "education")
    if edu:
        paras.append("My education: %s." % _nice(edu[0]))
    sk = skills(parsed)
    if sk:
        paras.append("I work with %s." % ", ".join(sk[:8]))
    built = [l for key in ("projects", "experience") for l in _items(parsed, key)][:3]
    if built:
        paras.append("Things I have worked on:\n" + "\n".join("- " + _nice(l) for l in built))
    if target.strip():
        paras.append("I am looking for %s roles and would be glad to hear from you." % target.strip())
    return "\n\n".join(paras)


def featured(parsed):
    """Projects and links the person can feature on the profile."""
    out = []
    for line in _items(parsed, "projects"):
        links = [m.group(0).rstrip(".,)") for m in _URL.finditer(line)]
        title = re.split(r"\s\|\s|:|;", line)[0].strip()[:80]
        out.append({"title": title, "line": _nice(line), "links": links})
    return out[:6]


def checklist(parsed):
    """Static advice plus facts about this CV: [{"text", "level"}] with level info or todo."""
    contact = profile_edit.with_contact(parsed).get("contact") or {}
    name = contact.get("name") or "yourname"
    handle = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "yourname"
    has_linkedin = any("linkedin.com" in (l or "").lower() for l in contact.get("links", []))
    items = []
    if not skills(parsed):
        items.append({"level": "todo", "text": "Your CV has no Skills section yet. Add one in tab 1; LinkedIn skills come from it."})
    if not _items(parsed, "projects") and not _items(parsed, "experience"):
        items.append({"level": "todo", "text": "Add at least one project or job to your CV first; the About and Featured parts use them."})
    if has_linkedin:
        items.append({"level": "info", "text": "Your CV already has your LinkedIn address. Keep the facts on both the same."})
    else:
        items.append({"level": "todo", "text": "Add your LinkedIn address to the CV (tab 1, Your details) once the profile is ready."})
    items += [
        {"level": "todo", "text": "Make the profile web address short, like linkedin.com/in/%s (Edit public profile and URL)." % handle},
        {"level": "todo", "text": "Use a clear, plain photo of your face. Recruiters open profiles with photos far more often."},
        {"level": "todo", "text": "Put the headline above first. Do not leave it as just your college or 'Student'."},
        {"level": "todo", "text": "Add the skills below, and pin your best three."},
        {"level": "todo", "text": "Add your projects in Featured, with a link if you have one (GitHub or a live page)."},
        {"level": "todo", "text": "Dates, college, marks and tools must match your CV exactly. Recruiters compare them."},
        {"level": "todo", "text": "Turn on 'Open to work' for recruiters only. The green photo frame is public; choose it only if you are happy for everyone to see."},
        {"level": "todo", "text": "Ask two seniors, teachers or project guides for a short recommendation."},
        {"level": "todo", "text": "Follow companies you like and connect with people from your college who work there. Add a one-line note when you connect."},
    ]
    return items


def advise(parsed, target=""):
    return {"headlines": headlines(parsed, target), "about": about(parsed, target), "skills": skills(parsed)[:MAX_SKILLS],
            "featured": featured(parsed), "checklist": checklist(parsed)}
