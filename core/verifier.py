"""Label every tailored line as Supported, Reworded or New.

This is the rule-based baseline of the "truth lens". It is deliberately cautious:
a wrongly flagged line only asks the user to confirm, while a wrongly accepted
false claim would break the product's promise. Where the rules cannot be sure,
they say "new". A model-based verifier can later reduce false flags, but it must
beat this baseline on the golden test set before it replaces it.

Labels: "supported" (same fact, same words), "reworded" (same fact, new words),
"new" (not provably in the resume).
"""

import re

from .keywords import tokens

SUPPORTED = "supported"
REWORDED = "reworded"
NEW = "new"

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
REWORD_OVERLAP = 0.5   # share of the new line's words that must come from the original
MAX_NOVEL_WORDS = 3    # new words allowed in a reworded line


def _numbers(text):
    return {n.replace(",", "") for n in _NUMBER.findall(text)}


def label_line(text, original, skill_terms=frozenset()):
    """Return (label, reason) for one tailored line against its source line."""
    if original is None:
        return NEW, "no source line in the resume"

    new_tokens = tokens(text)
    old_tokens = tokens(original)
    if new_tokens == old_tokens:
        return SUPPORTED, "same words as the original"

    novel_numbers = _numbers(text) - _numbers(original)
    if novel_numbers:
        return NEW, "number not in the original: %s" % ", ".join(sorted(novel_numbers))

    new_set, old_set = set(new_tokens), set(old_tokens)
    novel = new_set - old_set
    flagged = {t for t in novel if t in skill_terms}
    if flagged:
        return NEW, "skill or tool not in the original: %s" % ", ".join(sorted(flagged))

    overlap = len(new_set & old_set) / len(new_set) if new_set else 0.0
    if overlap >= REWORD_OVERLAP and len(novel) <= MAX_NOVEL_WORDS:
        return REWORDED, "same facts, %d new word(s)" % len(novel)
    return NEW, "too different from the original to confirm automatically"


def verify_output(tailored, items, skill_terms=frozenset()):
    """Return one claim per bullet: {line_ref, text, source_id, label, reason}.

    tailored: validated tailoring output. items: {source_id: original text}.
    A bullet the AI called "kept" or "reworded" is still checked by the rules;
    the stricter label wins, so the AI cannot vouch for itself.
    """
    claims = []
    for si, section in enumerate(tailored["sections"]):
        for bi, bullet in enumerate(section["bullets"]):
            original = items.get(bullet.get("source_id")) if bullet.get("source_id") else None
            label, reason = label_line(bullet["text"], original, skill_terms)
            if bullet.get("change") == "new":
                label, reason = NEW, "marked new by the writer"
            claims.append(
                {
                    "line_ref": "s%d.b%d" % (si, bi),
                    "text": bullet["text"],
                    "source_id": bullet.get("source_id"),
                    "label": label,
                    "reason": reason,
                }
            )
    return claims


def can_export(claims, decisions):
    """True when every New line has been confirmed or removed by the user.

    decisions: {line_ref: "confirmed" | "removed"}. Anything else is pending.
    """
    for claim in claims:
        if claim["label"] == NEW and decisions.get(claim["line_ref"]) not in ("confirmed", "removed"):
            return False
    return True


def final_lines(claims, decisions):
    """The lines that go into the exported file: everything except removed lines."""
    return [c for c in claims if decisions.get(c["line_ref"]) != "removed"]
