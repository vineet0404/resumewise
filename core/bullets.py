"""Tips to make a CV line stronger. Own code, no AI, nothing invented.

The checker only points at problems and asks questions ("How many test cases?"). It never writes numbers,
tools or results for the person: only they know the facts. Rules are for English lines; lines written mostly
in another script (Hindi, Telugu...) are left alone.
"""

import re

_BULLET_SECTIONS = ("experience", "projects", "achievements")
_TEXT_SECTIONS = _BULLET_SECTIONS + ("summary",)

_WEAK = re.compile(r"^(worked\s+(on|with)|responsible\s+for|was\s+responsible|helped(\s+(with|to|in))?|assisted(\s+(with|in))?|"
                   r"involved\s+in|participated\s+in|part\s+of|duties\s+included|tasked\s+with|in\s+charge\s+of|handled\s+various)\b", re.I)
_FIRST_PERSON = re.compile(r"^(i|my|we|our)\b|\b(i am|i was|i have|i worked|i built|i did)\b", re.I)
_VAGUE = re.compile(r"\b(various|etc\.?|many\s+things|several\s+things|good\s+knowledge|hard[- ]?working|team\s+player|"
                    r"detail[- ]oriented|go[- ]getter|results?[- ]driven|dynamic|passionate\s+about)\b", re.I)
_PASSIVE = re.compile(r"\b(was|were|been|is|are)\s+(\w+ly\s+)?(done|made|tested|created|built|developed|handled|used|fixed|written|prepared|completed)\b", re.I)
_NUMBER = re.compile(r"\d|%")

_VERBS = {
    "test": ["Tested", "Verified", "Reported", "Automated"],
    "build": ["Built", "Developed", "Implemented", "Designed"],
    "fix": ["Fixed", "Resolved", "Debugged"],
    "improve": ["Improved", "Reduced", "Optimised", "Increased"],
    "lead": ["Led", "Coordinated", "Organised", "Mentored"],
    "write": ["Wrote", "Documented", "Prepared"],
    "analyse": ["Analysed", "Evaluated", "Compared"],
}
_DEFAULT_VERBS = ["Built", "Designed", "Tested", "Wrote", "Improved", "Led"]
_TOPICS = (
    ("test", re.compile(r"\b(test|testing|qa|bug|defect|selenium|automation)\w*", re.I)),
    ("fix", re.compile(r"\b(fix|debug|resolv|issue|error)\w*", re.I)),
    ("improve", re.compile(r"\b(improv|reduc|increas|faster|optimi[sz]|speed|performance)\w*", re.I)),
    ("lead", re.compile(r"\b(team|lead|led|manag|coordinat|mentor)\w*", re.I)),
    ("write", re.compile(r"\b(document|report|content|blog|wrote|writing)\w*", re.I)),
    ("analyse", re.compile(r"\b(analy|research|survey|data)\w*", re.I)),
    ("build", re.compile(r"\b(build|built|develop|creat|design|app|website|api|module|system|project)\w*", re.I)),
)
_ASKS = (
    (re.compile(r"\b(test|testing|qa|bug|defect)\w*", re.I), "How many test cases did you write, or how many bugs did you find?"),
    (re.compile(r"\b(user|customer|client|student|visitor)s?\b", re.I), "How many users, customers or students?"),
    (re.compile(r"\b(improv|reduc|increas|faster|optimi[sz]|speed|performance)\w*", re.I), "By how much: what percent, or how many minutes or hours saved?"),
    (re.compile(r"\b(team|lead|led|manag|coordinat|mentor)\w*", re.I), "How many people were in the team?"),
    (re.compile(r"\b(api|page|screen|module|feature|report|dashboard)s?\b", re.I), "How many pages, APIs, modules or features?"),
    (re.compile(r"\b(data|record|row|file|document)s?\b", re.I), "How much data: how many records or files?"),
)


def _mostly_english(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    return sum(1 for c in letters if c.isascii()) / len(letters) >= 0.7


def _verbs_for(text):
    for key, pattern in _TOPICS:
        if pattern.search(text):
            return _VERBS[key]
    return _DEFAULT_VERBS


def check_line(text, section="experience"):
    """List of tips for one line: {"code", "tip", optional "asks", optional "verbs"}."""
    text = (text or "").strip()
    if not text or section not in _TEXT_SECTIONS or not _mostly_english(text):
        return []
    tips = []
    words = text.split()
    bullet = section in _BULLET_SECTIONS
    if bullet and _WEAK.match(text):
        tips.append({"code": "weak_start", "tip": "This starts with a weak phrase. Start with what YOU did, using one strong verb.",
                     "verbs": _verbs_for(text)})
    if _FIRST_PERSON.search(text):
        tips.append({"code": "first_person", "tip": "Leave out 'I', 'my' and 'we'. Write 'Built a login page', not 'I built a login page'."})
    if bullet and _PASSIVE.search(text):
        tips.append({"code": "passive", "tip": "Passive wording hides who did the work. Say what you did, for example 'Tested the module' instead of 'The module was tested'."})
    if _VAGUE.search(text):
        tips.append({"code": "vague", "tip": "This has a vague word (like 'various', 'etc', 'team player'). Replace it with something specific and true."})
    if bullet and (len(words) < 3 or (len(words) < 4 and not _NUMBER.search(text))):
        tips.append({"code": "too_short", "tip": "Too short. Say what you did and what came out of it."})
    if len(words) > 30 or len(text) > 220:
        tips.append({"code": "too_long", "tip": "Long line. Split it into two shorter points; the first few words are what people read."})
    if bullet and len(words) >= 4 and not _NUMBER.search(text):
        asks = [q for pattern, q in _ASKS if pattern.search(text)][:2] or ["Is there a number you can add: how many, how much, how often, how long? Add it only if it is true."]
        tips.append({"code": "no_number", "tip": "No number. A number makes a line believable (only add one that is true).", "asks": asks})
    return tips


def repeated_starts(items):
    """Words that start 3 or more bullets, for example 'Worked' x4. `items` is [(section, text)]."""
    count = {}
    for section, text in items:
        if section in _BULLET_SECTIONS and _mostly_english(text) and text.split():
            first = re.sub(r"[^a-z]", "", text.split()[0].lower())
            if first:
                count[first] = count.get(first, 0) + 1
    return sorted(w for w, n in count.items() if n >= 3)


def review(parsed):
    """Tips for a whole CV: {"lines": [{"id","section","text","tips"}], "total", "flagged", "repeated"}."""
    lines, items, total = [], [], 0
    for section in parsed["sections"]:
        for item in section["items"]:
            total += 1
            items.append((section["key"], item["text"]))
            tips = check_line(item["text"], section["key"])
            if tips:
                lines.append({"id": item["id"], "section": section["key"], "text": item["text"], "tips": tips})
    return {"lines": lines, "total": total, "flagged": len(lines), "repeated": repeated_starts(items)}
