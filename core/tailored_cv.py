"""Turn an AI-tailored result plus the user's decisions into a normal parsed resume.

The result can then be shown in any template, scanned by the ATS check, or written
to Word, exactly like the user's own CV. Rules:
- a line the user removed is left out
- a line labelled "new" cannot be exported until the user confirmed or removed it
- the name and contact details always come from the user's own CV, never from the AI
"""

from . import profile_edit, verifier


def pending_new(claims, decisions):
    """Line refs labelled new that the user has not decided yet."""
    return [c["line_ref"] for c in claims
            if c["label"] == verifier.NEW and decisions.get(c["line_ref"]) not in ("confirmed", "removed")]


def build_resume(base_parsed, output, decisions):
    """base_parsed: the user's own parsed CV. output: {"sections": [...]} from the AI."""
    resume = profile_edit.with_contact(base_parsed)
    sections = []
    for si, section in enumerate(output.get("sections", [])):
        key = str(section.get("type", "")).strip().lower()
        items = []
        for bi, bullet in enumerate(section.get("bullets", [])):
            if decisions.get("s%d.b%d" % (si, bi)) == "removed":
                continue
            items.append({"id": "%s.%d" % (key, len(items) + 1), "text": bullet["text"]})
        if items:
            sections.append({"key": key,
                             "title": profile_edit.SECTION_TITLES.get(key, key.title()),
                             "items": items})
    resume["sections"] = sections
    return resume
