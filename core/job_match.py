"""Match one CV against one job description, in plain words for the screen.

Same scoring as matching.py (own code, no AI). Adds readable term names and the
CV line that proves each covered term, so the person can see why.
"""

import re

from . import keywords, matching, resume_parser

_TAGS = re.compile(r"<[^>]{1,200}>")

_WEAK_SECTIONS = ("skills", "languages", "summary")


def analyse(parsed, job_text):
    job_text = _TAGS.sub(" ", job_text)  # text copied from a web page may carry tags
    items = resume_parser.all_items(parsed)
    reqs = keywords.extract_requirements(job_text)
    raw = matching.score_match(items, reqs)
    names = keywords.original_forms([r["term"] for r in reqs], job_text)
    required = {r["term"]: bool(r.get("required")) for r in reqs}
    section_of = {i["id"]: s["key"] for s in parsed["sections"] for i in s["items"]}
    covered = []
    for c in raw["covered"]:
        ids = sorted(c["evidence_ids"], key=lambda i: (section_of.get(i) in _WEAK_SECTIONS, i))
        covered.append({"term": c["term"], "name": names[c["term"]], "required": required[c["term"]],
                        "evidence_id": ids[0], "line": items[ids[0]]})
    missing = [{"term": t, "name": names[t], "required": required[t]} for t in raw["missing"]]
    return {"score": raw["score"], "covered": covered, "missing": missing}
