"""Text helpers: tokenising, light stemming, and requirement extraction.

Requirement extraction is deliberately simple and explainable: it counts terms
in a job description and gives extra weight to terms in lines that say a skill
is required. A trained model can replace it later behind the same function.
"""

import re

STOPWORDS = frozenset(
    """a an and are as at be been by can do for from has have in into is it its of on or our
    that the their this to was we will with you your us who what which about across after also
    all any both each etc more most must new not only other out over per role roles such than
    then there these they those through up use using very well within work working years year
    candidate candidates looking required requirements responsibilities job team join company
    ability strong good knowledge experience skills skill plus preferred should including
    related relevant""".split()
)

_REQUIRED_HINT = re.compile(
    r"\b(required|must|mandatory|should have|need to|knowledge of|experience (?:with|in)|proficien\w+|expertise)\b",
    re.IGNORECASE,
)
_NICE_HINT = re.compile(r"\b(plus|preferred|nice to have|good to have|bonus|desirable)\b", re.IGNORECASE)

_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.\-]*[a-z0-9+#]|[a-z0-9]")


def stem(word):
    """Very small stemmer: plurals and common verb endings."""
    w = word
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    for suffix in ("ing", "ed", "s"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            if suffix == "s" and w.endswith(("ss", "us", "is")):
                return w
            return w[: -len(suffix)]
    return w


def tokens(text):
    """Lower-case tokens, stemmed, stopwords removed. Keeps c++, c#, node.js style terms."""
    out = []
    for raw in _TOKEN.findall(text.lower()):
        raw = raw.strip(".-")
        if not raw or raw in STOPWORDS:
            continue
        out.append(stem(raw))
    return out


def token_stream(text):
    """Stemmed tokens in order, with None where a stopword was removed.

    Keeping the gaps lets us build two-word phrases only from words that were
    really next to each other ("test cases"), never across "and" or "of".
    """
    out = []
    for raw in _TOKEN.findall(text.lower()):
        raw = raw.strip(".-")
        if not raw:
            continue
        out.append(None if raw in STOPWORDS else stem(raw))
    return out


def grams(text):
    """Set of single tokens plus adjacent two-word phrases."""
    stream = token_stream(text)
    found = {t for t in stream if t}
    found.update("%s %s" % (a, b) for a, b in zip(stream, stream[1:]) if a and b)
    return found


def extract_requirements(job_text, max_terms=15):
    """Return [{"term", "weight", "required"}] for the job description.

    Terms are single tokens or two-word phrases. Weight is 1 for a plain mention,
    plus 2 if it appears in a line that says it is required, minus nothing for
    "plus/preferred" lines (those are marked required=False).
    """
    scores = {}
    required_terms = set()
    optional_terms = set()
    for line in re.split(r"[\n.;]", job_text):
        line_grams = grams(line)
        if not line_grams:
            continue
        is_required = bool(_REQUIRED_HINT.search(line))
        is_nice = bool(_NICE_HINT.search(line))
        for gram in line_grams:
            bonus = 2 if is_required else 0
            scores[gram] = scores.get(gram, 0) + 1 + bonus
            if is_required:
                required_terms.add(gram)
            if is_nice:
                optional_terms.add(gram)

    # Prefer phrases over their parts: drop a single word if a kept phrase contains it with equal score.
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    chosen = []
    covered_words = set()
    for term, score in ranked:
        words = term.split()
        if len(words) == 1 and term in covered_words:
            continue
        if len(words) == 1 and len(term) < 3 and not re.search(r"[0-9+#]", term):
            continue
        chosen.append((term, score))
        if len(words) == 2:
            covered_words.update(words)
        if len(chosen) >= max_terms:
            break

    return [
        {
            "term": term,
            "weight": score,
            "required": term in required_terms and term not in optional_terms,
        }
        for term, score in chosen
    ]


def original_forms(terms, text):
    """{term: the words as the job description wrote them}. "test case" becomes "test cases" again.

    Terms are stemmed for matching; people should see normal words. If a word cannot be
    found in the text (it should always be), the stemmed word is kept.
    """
    seen = {}
    for m in _TOKEN.finditer(text.lower()):
        raw = m.group().strip(".-")
        if raw and raw not in STOPWORDS:
            seen.setdefault(stem(raw), text[m.start():m.end()].strip(".-"))
    return {t: " ".join(seen.get(w, w) for w in t.split()) for t in terms}
