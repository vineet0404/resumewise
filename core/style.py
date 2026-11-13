"""Keep tailored lines sounding like the user, not like a template.

Three checks, all rule-based and in our own code:

1. Cliche filter: stock words that make every AI-written resume sound alike.
   A cliche is allowed when the user already used it in their own resume.
2. Style profile: how the user writes (line length, full stops, numbers).
   New lines that stray far from it are flagged.
3. Minimal change: a "reworded" line must keep most of the user's own words.

These return warnings for the review screen. They never block a line by
themselves; the user decides. Nothing here claims to beat any AI detector.
"""

import re

from .keywords import tokens

# Phrases and words that appear far more in generic AI resumes than in real ones.
CLICHES = (
    "spearheaded", "leveraged", "leverage", "leveraging", "orchestrated", "pioneered",
    "revolutionized", "championed", "streamlined", "synergy", "synergies",
    "results-driven", "detail-oriented", "dynamic professional", "proven track record",
    "passionate", "go-getter", "team player", "self-motivated", "think outside the box",
    "cutting-edge", "state-of-the-art", "seamlessly", "robust", "delve", "tapestry",
    "testament", "ever-evolving", "fast-paced", "utilized", "utilize", "utilizing",
    "instrumental in", "adept at", "well-versed", "highly motivated",
)

_WORD = re.compile(r"[A-Za-z][A-Za-z\-']*")
_HAS_NUMBER = re.compile(r"\d")

MIN_KEEP_WORDS = 0.6    # a reworded line keeps at least this share of the original's words
LENGTH_SLACK_WORDS = 10  # extra words allowed over the user's longest line


def _words(text):
    return _WORD.findall(text.lower())


def find_cliches(text, allowed=()):
    """Cliches in `text` that the user did not already use. `allowed` is a set of strings."""
    lowered = text.lower()
    allowed_lower = {a.lower() for a in allowed}
    found = []
    for phrase in CLICHES:
        if phrase in allowed_lower:
            continue
        if re.search(r"(?<![A-Za-z])" + re.escape(phrase) + r"(?![A-Za-z])", lowered):
            found.append(phrase)
    return found


def cliches_in_user_text(items):
    """Cliches the user already wrote themselves, so we never flag their own words."""
    joined = " \n".join(items).lower()
    return {p for p in CLICHES if re.search(r"(?<![A-Za-z])" + re.escape(p) + r"(?![A-Za-z])", joined)}


def style_profile(items):
    """A small description of how the user writes. `items` is a list of their lines."""
    lines = [t.strip() for t in items if t and t.strip()]
    if not lines:
        return {"lines": 0, "avg_words": 0.0, "max_words": 0, "ends_with_period": 0.0, "has_number": 0.0}
    counts = [len(_words(t)) for t in lines]
    return {
        "lines": len(lines),
        "avg_words": sum(counts) / len(counts),
        "max_words": max(counts),
        "ends_with_period": sum(1 for t in lines if t.endswith(".")) / len(lines),
        "has_number": sum(1 for t in lines if _HAS_NUMBER.search(t)) / len(lines),
    }


def check_line(text, profile, allowed_cliches=()):
    """Return a list of {"flag", "detail"} warnings for one new or reworded line."""
    warnings = []
    for phrase in find_cliches(text, allowed_cliches):
        warnings.append({"flag": "cliche", "detail": "stock phrase: %s" % phrase})
    if profile.get("lines", 0) >= 3:
        n = len(_words(text))
        if n > profile["max_words"] + LENGTH_SLACK_WORDS:
            warnings.append({"flag": "long", "detail": "much longer than your other lines (%d words)" % n})
        stripped = text.strip()
        if profile["ends_with_period"] <= 0.2 and stripped.endswith("."):
            warnings.append({"flag": "full_stop", "detail": "your lines do not end with a full stop"})
        if profile["ends_with_period"] >= 0.8 and stripped and not stripped.endswith("."):
            warnings.append({"flag": "full_stop", "detail": "your lines end with a full stop"})
    return warnings


def keep_ratio(original, new):
    """Share of the original's words that are still in the new line (0 to 1)."""
    old = set(tokens(original))
    if not old:
        return 1.0
    return len(old & set(tokens(new))) / len(old)


def check_output(lines, originals):
    """Style warnings for a tailored resume.

    `lines`: list of {"text", "source_id", "change"} (the bullets from the AI output).
    `originals`: {id: text} of the user's own lines.
    Returns a list of {"index", "flag", "detail"}.
    """
    own = list(originals.values())
    profile = style_profile(own)
    allowed = cliches_in_user_text(own)
    results = []
    for index, line in enumerate(lines):
        change = line.get("change")
        text = line.get("text", "")
        if change == "kept":
            continue
        for w in check_line(text, profile, allowed):
            results.append({"index": index, **w})
        if change == "reworded":
            source = originals.get(line.get("source_id"))
            if source is not None and keep_ratio(source, text) < MIN_KEEP_WORDS:
                results.append({
                    "index": index,
                    "flag": "rewritten",
                    "detail": "changed a lot; keep more of your own words",
                })
    return results
