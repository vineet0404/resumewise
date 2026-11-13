"""Tailor a parsed resume to a job description with the AI gateway, safely.

What goes to the AI: only the numbered resume lines (no name, no contact header)
and the job text, both with emails, phones and links replaced by placeholders.
What comes back is validated, restored, fact-checked by our own verifier and
style-checked before the user sees it. The AI can never vouch for itself.
"""

from . import keywords, redact, resume_parser, style, tailoring, verifier

INSTRUCTIONS = (
    "Task: tailor the resume lines to the job description.\n"
    "Rules:\n"
    "- Use only facts in the resume lines. Never add a skill, tool, number, employer or date that is not there.\n"
    "- Prefer keeping a line exactly as written. Reword only to match the job's wording, with the fewest changes.\n"
    "- Keep the writer's own style: same length, same punctuation, no stock phrases.\n"
    "- Each bullet needs source_id (the line id it came from) and change: kept, reworded or new. "
    "Use new only if a line cannot come from the resume, and then source_id must be null.\n"
    "- In gaps, list job requirements the resume does not show, with honest advice. Do not invent experience.\n"
    "Reply with JSON only, in this shape:\n"
    '{"sections":[{"type":"projects","bullets":[{"text":"...","source_id":"projects.1",'
    '"change":"kept","keywords_used":["..."]}]}],"gaps":[{"requirement":"...","advice":"..."}]}'
)


def _skill_terms(job_text):
    terms = set()
    for req in keywords.extract_requirements(job_text):
        terms.update(keywords.tokens(req["term"]))
    return terms


def tailor(parsed, job_text, gateway):
    # Personal details (date of birth, gender, ...) are never sent to the AI.
    items = {i["id"]: i["text"] for sec in parsed["sections"] if sec["key"] != "personal" for i in sec["items"]}
    if not items:
        raise ValueError("the resume has no lines to tailor")
    known = [h for h in parsed.get("header", [])[:1]]  # the name line, if any
    resume_block = "\n".join("%s: %s" % (i, t) for i, t in items.items())
    safe_resume, mapping = redact.redact(resume_block, known)
    safe_job, job_map = redact.redact(job_text)
    mapping.update(job_map)

    ids = set(items)
    output = gateway.run(
        "tailor", INSTRUCTIONS, {"resume": safe_resume, "job": safe_job},
        validator=lambda out: tailoring.validate_tailoring(out, ids),
    )
    for section in output["sections"]:
        for bullet in section["bullets"]:
            bullet["text"] = redact.restore(bullet["text"], mapping)

    claims = verifier.verify_output(output, items, _skill_terms(job_text))
    bullets = [b for s in output["sections"] for b in s["bullets"]]
    warnings = style.check_output(bullets, items)
    return {
        "sections": output["sections"],
        "gaps": output.get("gaps", []),
        "claims": claims,
        "style_warnings": warnings,
        "needs_review": sum(1 for c in claims if c["label"] == verifier.NEW),
        "cost_paise": gateway.spent_paise,
    }
