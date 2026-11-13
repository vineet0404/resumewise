"""Remove personal details from text before it is sent to any AI provider.

redact() swaps emails, phone numbers and links for placeholders such as
[EMAIL_1] and returns a mapping. restore() puts the originals back on our own
server after the AI has answered. The AI never needs the real values.

Names and addresses cannot be found reliably with patterns, so callers pass
them in through `known_values` (for example the name the user typed).
"""

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Indian mobile numbers with optional +91 or 0 prefix, and common separators.
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s\-]?|0)?[6-9]\d{4}[\s\-]?\d{5}(?!\d)")
_URL = re.compile(r"(?:https?://|www\.)[^\s)\]>,;]+", re.IGNORECASE)
_SOCIAL = re.compile(
    r"(?<![\w/])(?:linkedin\.com|github\.com)/[^\s)\]>,;]+", re.IGNORECASE
)

_PLACEHOLDER = re.compile(r"\[(?:EMAIL|PHONE|LINK|NAME|VALUE)_\d+\]")


def redact(text, known_values=()):
    """Return (redacted_text, mapping). mapping is {placeholder: original}."""
    mapping = {}
    counters = {}

    def make(kind, original):
        for placeholder, value in mapping.items():
            if value == original and placeholder.startswith("[" + kind + "_"):
                return placeholder
        counters[kind] = counters.get(kind, 0) + 1
        placeholder = "[%s_%d]" % (kind, counters[kind])
        mapping[placeholder] = original
        return placeholder

    # Longest known values first so "Aarti Sharma" is replaced before "Aarti".
    for value in sorted({v for v in known_values if v and v.strip()}, key=len, reverse=True):
        pattern = re.compile(re.escape(value.strip()), re.IGNORECASE)
        text = pattern.sub(lambda m: make("NAME", m.group(0)), text)

    text = _EMAIL.sub(lambda m: make("EMAIL", m.group(0)), text)
    text = _URL.sub(lambda m: make("LINK", m.group(0)), text)
    text = _SOCIAL.sub(lambda m: make("LINK", m.group(0)), text)
    text = _PHONE.sub(lambda m: make("PHONE", m.group(0)), text)
    return text, mapping


def restore(text, mapping):
    """Put original values back in place of placeholders."""
    return _PLACEHOLDER.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)


def contains_pii(text):
    """True if the text still has an email, phone number or link."""
    return bool(_EMAIL.search(text) or _PHONE.search(text) or _URL.search(text) or _SOCIAL.search(text))
