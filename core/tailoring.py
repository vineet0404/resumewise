"""Validate the JSON an AI step returns for a tailored resume.

The AI may only reword or reorder what the user wrote. Every bullet must say
where it came from (`source_id`) unless it is explicitly marked "new". Anything
that fails validation is rejected before the user sees it.

Expected shape:

{
  "sections": [
    {"type": "projects",
     "bullets": [{"text": "...", "source_id": "projects.1",
                  "change": "kept" | "reworded" | "new",
                  "keywords_used": ["..."]}]}
  ],
  "gaps": [{"requirement": "...", "advice": "..."}]
}
"""

ALLOWED_CHANGES = ("kept", "reworded", "new")
MAX_BULLET_CHARS = 400
MAX_BULLETS_TOTAL = 60


def validate_tailoring(output, resume_ids):
    """Return a list of error strings. An empty list means the output is valid."""
    errors = []
    if not isinstance(output, dict):
        return ["output must be an object"]
    sections = output.get("sections")
    if not isinstance(sections, list) or not sections:
        return ["sections must be a non-empty list"]

    total = 0
    for si, section in enumerate(sections):
        where = "sections[%d]" % si
        if not isinstance(section, dict):
            errors.append("%s must be an object" % where)
            continue
        if not isinstance(section.get("type"), str) or not section["type"].strip():
            errors.append("%s.type must be a non-empty string" % where)
        bullets = section.get("bullets")
        if not isinstance(bullets, list):
            errors.append("%s.bullets must be a list" % where)
            continue
        for bi, bullet in enumerate(bullets):
            total += 1
            path = "%s.bullets[%d]" % (where, bi)
            if not isinstance(bullet, dict):
                errors.append("%s must be an object" % path)
                continue
            text = bullet.get("text")
            if not isinstance(text, str) or not text.strip():
                errors.append("%s.text must be a non-empty string" % path)
            elif len(text) > MAX_BULLET_CHARS:
                errors.append("%s.text is longer than %d characters" % (path, MAX_BULLET_CHARS))
            change = bullet.get("change")
            if change not in ALLOWED_CHANGES:
                errors.append("%s.change must be one of %s" % (path, ", ".join(ALLOWED_CHANGES)))
                continue
            source_id = bullet.get("source_id")
            if change == "new":
                if source_id is not None:
                    errors.append("%s is marked new so source_id must be null" % path)
            else:
                if not isinstance(source_id, str) or source_id not in resume_ids:
                    errors.append("%s.source_id %r is not in the resume" % (path, source_id))
            keywords = bullet.get("keywords_used", [])
            if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
                errors.append("%s.keywords_used must be a list of strings" % path)

    if total > MAX_BULLETS_TOTAL:
        errors.append("too many bullets (%d, maximum %d)" % (total, MAX_BULLETS_TOTAL))

    gaps = output.get("gaps", [])
    if not isinstance(gaps, list) or not all(
        isinstance(g, dict) and isinstance(g.get("requirement"), str) for g in gaps
    ):
        errors.append("gaps must be a list of objects with a requirement")
    return errors
