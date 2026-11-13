"""Score how well a resume covers a job's requirements, and show the evidence."""

from .keywords import grams


def _covers(item_grams, term):
    """A term is covered if the item has it, or has every word of a phrase."""
    if term in item_grams:
        return True
    words = term.split()
    return len(words) > 1 and all(w in item_grams for w in words)


def score_match(items, requirements):
    """items: {item_id: text}. requirements: output of extract_requirements.

    Returns {"score": 0-100, "covered": [{"term","evidence_ids"}], "missing": [term]}.
    Required terms count double. A term is covered only if some resume item
    contains it, so the score cannot be raised by wording alone.
    """
    item_grams = {item_id: grams(text) for item_id, text in items.items()}
    covered = []
    missing = []
    earned = 0.0
    total = 0.0
    for req in requirements:
        weight = req["weight"] * (2 if req.get("required") else 1)
        total += weight
        evidence = sorted(i for i, g in item_grams.items() if _covers(g, req["term"]))
        if evidence:
            earned += weight
            covered.append({"term": req["term"], "evidence_ids": evidence})
        else:
            missing.append(req["term"])
    score = 0 if total == 0 else int(round(100 * earned / total))
    return {"score": score, "covered": covered, "missing": missing}
