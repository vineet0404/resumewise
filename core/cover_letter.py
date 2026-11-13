"""A cover letter built only from what is in the CV and what the person types.

No AI and nothing invented: the letter quotes real CV lines that match the job, and
never mentions a skill the CV does not show. The person can edit every word after.
"""

from . import profile_edit

MAX_LINES = 4
_SKIP_FOR_EXAMPLES = ("skills", "languages", "summary", "education", "certifications")


def _nice(line):
    return line.replace(" | ", ", ").strip().rstrip(".")


def write(parsed, analysis, title, company="", why="", manager=""):
    """Return {"text", "left_out"}. `analysis` comes from job_match.analyse."""
    cv = profile_edit.with_contact(parsed)
    contact = cv.get("contact") or {}
    name = contact.get("name") or "Your Name"
    greeting = "Dear %s," % (manager.strip() if manager.strip() else "Hiring Manager")
    role = "the %s position" % title.strip() if title.strip() else "the open position"
    opening = "I am writing to apply for %s%s." % (role, " at %s" % company.strip() if company.strip() else "")

    lines, used = [], set()
    ranked = sorted(analysis["covered"], key=lambda c: (not c["required"], c["term"]))
    for c in ranked:
        if c["line"] in used:
            continue
        used.add(c["line"])
        lines.append(c["line"])
        if len(lines) >= MAX_LINES:
            break
    parts = [greeting, opening]
    if lines:
        parts.append("Some things from my background that match what you are looking for:\n" + "\n".join("- " + _nice(l) for l in lines))
    edu = [i["text"] for s in parsed["sections"] if s["key"] == "education" for i in s["items"]]
    if edu:
        parts.append("My education: %s." % _nice(edu[0]))
    if why.strip():
        parts.append(why.strip())
    parts.append("I would be glad to talk about how I can help your team. Thank you for your time.")
    sign = ["Sincerely,", name]
    reach = " | ".join(x for x in (contact.get("email"), contact.get("phone")) if x)
    if reach:
        sign.append(reach)
    parts.append("\n".join(sign))
    left_out = [m["name"] for m in analysis["missing"] if m["required"]]
    return {"text": "\n\n".join(parts), "left_out": left_out}
