"""Our own PDF reader, part 2: fonts.

A PDF shows text as numbers ("character codes") that only make sense through the font. This file turns
the codes of a string into real characters and says how wide each one is, so `pdftext.py` can place
the text on the page.

- simple fonts (Type1, TrueType, Type3): one byte per character, an encoding (WinAnsi, MacRoman,
  Standard, plus "Differences" given by glyph names) or a /ToUnicode map
- composite fonts (Type0): two bytes per character (or whatever the CMap says), almost always with a
  /ToUnicode map (every modern producer: Chrome, Word, Google Docs, Canva, LibreOffice, LaTeX)

When no mapping exists the character becomes U+FFFD, and the caller counts those: a page that is mostly
unreadable is handed to OCR instead of returning rubbish.
"""

import re
import unicodedata

from .pdfread import Lexer, Name, Op, PdfError, Stream, decode_stream

UNKNOWN = "�"

# ------------------------------------------------------------------ glyph names -> characters

_NAMES = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#", "dollar": "$", "percent": "%",
    "ampersand": "&", "quotesingle": "'", "parenleft": "(", "parenright": ")", "asterisk": "*",
    "plus": "+", "comma": ",", "hyphen": "-", "period": ".", "slash": "/", "colon": ":",
    "semicolon": ";", "less": "<", "equal": "=", "greater": ">", "question": "?", "at": "@",
    "bracketleft": "[", "backslash": "\\", "bracketright": "]", "asciicircum": "^",
    "underscore": "_", "grave": "`", "braceleft": "{", "bar": "|", "braceright": "}",
    "asciitilde": "~", "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "bullet": "•", "endash": "–", "emdash": "—", "quoteleft": "‘",
    "quoteright": "’", "quotedblleft": "“", "quotedblright": "”",
    "quotesinglbase": "‚", "quotedblbase": "„", "ellipsis": "…", "fi": "ﬁ",
    "fl": "ﬂ", "ff": "ﬀ", "ffi": "ﬃ", "ffl": "ﬄ", "dagger": "†",
    "daggerdbl": "‡", "trademark": "™", "registered": "®", "copyright": "©",
    "degree": "°", "section": "§", "paragraph": "¶", "Euro": "€",
    "sterling": "£", "yen": "¥", "cent": "¢", "currency": "¤", "florin": "ƒ",
    "guillemotleft": "«", "guillemotright": "»", "guilsinglleft": "‹",
    "guilsinglright": "›", "exclamdown": "¡", "questiondown": "¿",
    "multiply": "×", "divide": "÷", "plusminus": "±", "mu": "µ",
    "onesuperior": "¹", "twosuperior": "²", "threesuperior": "³",
    "onequarter": "¼", "onehalf": "½", "threequarters": "¾",
    "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ", "germandbls": "ß",
    "oslash": "ø", "Oslash": "Ø", "dotlessi": "ı", "eth": "ð", "Eth": "Ð",
    "thorn": "þ", "Thorn": "Þ", "Lslash": "Ł", "lslash": "ł",
    "Scaron": "Š", "scaron": "š", "Zcaron": "Ž", "zcaron": "ž",
    "Ydieresis": "Ÿ", "perthousand": "‰", "tilde": "˜", "circumflex": "ˆ",
    "minus": "−", "arrowright": "→", "arrowleft": "←", "periodcentered": "·",
    "middot": "·", "nbspace": " ", "nonbreakingspace": " ", "sfthyphen": "-", "softhyphen": "-",
    "brokenbar": "¦", "logicalnot": "¬", "macron": "¯", "acute": "´",
    "cedilla": "¸", "dieresis": "¨", "ordfeminine": "ª", "ordmasculine": "º",
    "fraction": "⁄", "lozenge": "◊", "check": "✓", "checkmark": "✓",
    "square": "□", "blacksquare": "■", "circle": "○", "bullet.": "•",
    "rupee": "₹", "Rupee": "₹", "rupeeindian": "₹", "afii61352": "№",
    "summation": "∑", "infinity": "∞", "notequal": "≠", "lessequal": "≤",
    "greaterequal": "≥", "approxequal": "≈", "partialdiff": "∂", "radical": "√",
}
_ACCENTS = {
    "acute": "ACUTE", "grave": "GRAVE", "circumflex": "CIRCUMFLEX", "dieresis": "DIAERESIS",
    "tilde": "TILDE", "ring": "RING ABOVE", "cedilla": "CEDILLA", "caron": "CARON",
    "ogonek": "OGONEK", "macron": "MACRON", "breve": "BREVE", "dotaccent": "DOT ABOVE",
    "stroke": "STROKE", "hungarumlaut": "DOUBLE ACUTE",
}
_ACCENT_RE = re.compile(r"^([A-Za-z])(" + "|".join(_ACCENTS) + r")$")
_names_cache = {}


def glyph_char(name):
    """Character for a glyph name, or None."""
    if name in _names_cache:
        return _names_cache[name]
    out = _glyph_char(name)
    _names_cache[name] = out
    return out


def _glyph_char(name):
    if not name or name == ".notdef":
        return None
    if name in _NAMES:
        return _NAMES[name]
    if len(name) == 1 and name.isalpha() and name.isascii():
        return name
    base = name.split(".", 1)[0]
    if base != name:
        return glyph_char(base) if base else None
    if "_" in name:
        parts = [glyph_char(p) for p in name.split("_")]
        return "".join(parts) if all(parts) else None
    m = re.fullmatch(r"uni((?:[0-9A-Fa-f]{4})+)", name)
    if m:
        h = m.group(1)
        return "".join(chr(int(h[i:i + 4], 16)) for i in range(0, len(h), 4))
    m = re.fullmatch(r"u([0-9A-Fa-f]{4,6})", name)
    if m:
        cp = int(m.group(1), 16)
        return chr(cp) if cp <= 0x10FFFF else None
    m = _ACCENT_RE.match(name)
    if m:
        letter, accent = m.group(1), _ACCENTS[m.group(2)]
        kind = "CAPITAL" if letter.isupper() else "SMALL"
        try:
            return unicodedata.lookup("LATIN %s LETTER %s WITH %s" % (kind, letter.upper(), accent))
        except KeyError:
            return None
    return None


# ------------------------------------------------------------------ base encodings

def _winansi():
    table = []
    for code in range(256):
        if code < 32:
            table.append(None)
        elif code in (0x81, 0x8D, 0x8F, 0x90, 0x9D):
            table.append("•")
        elif code == 0xA0:
            table.append(" ")
        elif code == 0xAD:
            table.append("-")
        else:
            table.append(bytes([code]).decode("cp1252", "replace"))
    return table


def _macroman():
    table = []
    for code in range(256):
        table.append(None if code < 32 else bytes([code]).decode("mac_roman", "replace"))
    return table


_STANDARD_HIGH = {
    0xA1: "¡", 0xA2: "¢", 0xA3: "£", 0xA4: "⁄", 0xA5: "¥", 0xA6: "ƒ",
    0xA7: "§", 0xA8: "¤", 0xA9: "'", 0xAA: "“", 0xAB: "«", 0xAC: "‹",
    0xAD: "›", 0xAE: "ﬁ", 0xAF: "ﬂ", 0xB1: "–", 0xB2: "†", 0xB3: "‡",
    0xB4: "·", 0xB6: "¶", 0xB7: "•", 0xB8: "‚", 0xB9: "„", 0xBA: "”",
    0xBB: "»", 0xBC: "…", 0xBD: "‰", 0xBF: "¿", 0xC1: "`", 0xC2: "´",
    0xC3: "ˆ", 0xC4: "˜", 0xC5: "¯", 0xC6: "˘", 0xC7: "˙", 0xC8: "¨",
    0xCA: "˚", 0xCB: "¸", 0xCD: "˝", 0xCE: "˛", 0xCF: "ˇ", 0xD0: "—",
    0xE1: "Æ", 0xE3: "ª", 0xE8: "Ł", 0xE9: "Ø", 0xEA: "Œ", 0xEB: "º",
    0xF1: "æ", 0xF5: "ı", 0xF8: "ł", 0xF9: "ø", 0xFA: "œ", 0xFB: "ß",
}


def _standard():
    table = [None] * 256
    for code in range(32, 127):
        table[code] = chr(code)
    table[0x27] = "’"
    table[0x60] = "‘"
    for code, ch in _STANDARD_HIGH.items():
        table[code] = ch
    return table


_BASE = {"WinAnsiEncoding": _winansi(), "MacRomanEncoding": _macroman(), "StandardEncoding": _standard()}

# Symbol-type fonts that Word and others use for bullets (when no /ToUnicode says better)
_BULLET_FONTS = {
    "symbol": {0xB7: "•", 0xA7: "•", 0xA8: "•"},
    "wingdings": {0xA7: "▪", 0x6C: "●", 0x6E: "■", 0x71: "❑", 0x76: "❖",
                  0xD8: "➢", 0xFC: "✓", 0xFB: "✗", 0x9F: "•", 0xB7: "•",
                  0x75: "◆", 0x77: "⬥", 0xA8: "◻", 0x6F: "□", 0x70: "■"},
    "zapfdingbats": {0x6C: "●", 0x6E: "■", 0x34: "✔", 0x33: "✓", 0x75: "◆",
                     0x48: "★", 0xA8: "♣", 0x6F: "❏"},
}

# Private-use code points produced by Symbol/Wingdings ToUnicode maps (Word): turn into real bullets
PRIVATE_USE_BULLETS = {
    "": "•", "": "▪", "": "➢", "": "✓", "": "❖",
    "": "●", "": "■", "": "◻", "": "•", "": "✗",
    "": "◆", "": "□", "": "•", "": "-", "": " ",
}


# ------------------------------------------------------------------ CMaps

_HEX = re.compile(rb"<([0-9A-Fa-f\s]*)>")


def _utf16(b):
    if not b:
        return ""
    if len(b) == 1:
        return chr(b[0])
    try:
        return b.decode("utf-16-be")
    except UnicodeDecodeError:
        return b.decode("utf-16-be", "ignore")


class CMap:
    """Code -> text (ToUnicode) or code -> CID, parsed from a CMap program."""

    def __init__(self):
        self.char = {}          # code (int) -> str
        self.ranges = []        # (lo, hi, base string or list)
        self.cid_char = {}
        self.cid_ranges = []    # (lo, hi, cid0)
        self.space = []         # (nbytes, lo, hi) codespace ranges
        self.identity = False

    def parse(self, data):
        tokens = Lexer(data, 0, refs=False)
        stack = []
        count = 0
        while not tokens.at_end():
            count += 1
            if count > 400_000:
                break
            try:
                t = tokens.read()
            except PdfError:
                break
            if isinstance(t, Op):
                name = str(t)
                if name == "endcodespacerange":
                    for i in range(0, len(stack) - 1, 2):
                        lo, hi = stack[i], stack[i + 1]
                        if isinstance(lo, bytes) and isinstance(hi, bytes) and lo:
                            self.space.append((len(lo), int.from_bytes(lo, "big"), int.from_bytes(hi, "big")))
                    stack = []
                elif name == "endbfchar":
                    for i in range(0, len(stack) - 1, 2):
                        src, dst = stack[i], stack[i + 1]
                        if isinstance(src, bytes) and isinstance(dst, bytes):
                            self.char[int.from_bytes(src, "big")] = _utf16(dst)
                        elif isinstance(src, bytes) and isinstance(dst, Name):
                            ch = glyph_char(str(dst))
                            if ch:
                                self.char[int.from_bytes(src, "big")] = ch
                    stack = []
                elif name == "endbfrange":
                    i = 0
                    while i + 2 < len(stack):
                        lo, hi, dst = stack[i], stack[i + 1], stack[i + 2]
                        i += 3
                        if not (isinstance(lo, bytes) and isinstance(hi, bytes)):
                            continue
                        lo_i, hi_i = int.from_bytes(lo, "big"), int.from_bytes(hi, "big")
                        if hi_i < lo_i or hi_i - lo_i > 0xFFFF:
                            continue
                        if isinstance(dst, list):
                            for k, item in enumerate(dst):
                                if isinstance(item, bytes) and lo_i + k <= hi_i:
                                    self.char[lo_i + k] = _utf16(item)
                        elif isinstance(dst, bytes):
                            self.ranges.append((lo_i, hi_i, dst))
                    stack = []
                elif name == "endcidchar":
                    for i in range(0, len(stack) - 1, 2):
                        src, cid = stack[i], stack[i + 1]
                        if isinstance(src, bytes) and isinstance(cid, int):
                            self.cid_char[int.from_bytes(src, "big")] = cid
                    stack = []
                elif name == "endcidrange":
                    for i in range(0, len(stack) - 2, 3):
                        lo, hi, cid = stack[i], stack[i + 1], stack[i + 2]
                        if isinstance(lo, bytes) and isinstance(hi, bytes) and isinstance(cid, int):
                            self.cid_ranges.append((int.from_bytes(lo, "big"), int.from_bytes(hi, "big"), cid))
                    stack = []
                elif name.startswith("begin"):
                    stack = []
                continue
            stack.append(t)
            if len(stack) > 100_000:
                stack = stack[-1000:]
        return self

    def to_unicode(self, code):
        ch = self.char.get(code)
        if ch is not None:
            return ch
        for lo, hi, dst in self.ranges:
            if lo <= code <= hi:
                base = bytearray(dst)
                if base:
                    last = int.from_bytes(base[-2:], "big") if len(base) >= 2 else base[-1]
                    delta = code - lo
                    if len(base) >= 2:
                        base[-2:] = ((last + delta) & 0xFFFF).to_bytes(2, "big")
                    else:
                        base[-1] = (last + delta) & 0xFF
                    return _utf16(bytes(base))
        return None

    def to_cid(self, code):
        cid = self.cid_char.get(code)
        if cid is not None:
            return cid
        for lo, hi, c0 in self.cid_ranges:
            if lo <= code <= hi:
                return c0 + code - lo
        return None

    def split(self, data):
        """Cut a string into codes using the codespace ranges (default: 2 bytes)."""
        if not self.space:
            n = 2
            return [int.from_bytes(data[i:i + n], "big") for i in range(0, len(data) - n + 1, n)] + \
                   ([data[-1]] if len(data) % n else [])
        out = []
        i = 0
        lengths = sorted({s[0] for s in self.space})
        while i < len(data):
            for n in lengths:
                if i + n > len(data):
                    continue
                code = int.from_bytes(data[i:i + n], "big")
                if any(s[0] == n and s[1] <= code <= s[2] for s in self.space):
                    out.append(code)
                    i += n
                    break
            else:
                out.append(data[i])
                i += 1
        return out


# ------------------------------------------------------------------ widths for fonts without /Widths

def _approx_width(ch, courier=False, bold=False):
    if courier:
        return 600
    if ch == " ":
        return 278
    if ch in "ilj.,;:'|!":
        return 250
    if ch in "ftr()[]-":
        return 333
    if ch in "mwMW":
        return 833
    if ch.isupper():
        return 690
    if ch.isdigit():
        return 556
    return 520 if bold else 500


# ------------------------------------------------------------------ the font object

class Font:
    def __init__(self, pdf, fdict):
        self.pdf = pdf
        self.d = fdict if isinstance(fdict, dict) else {}
        r = pdf.resolve
        self.subtype = str(r(self.d.get("Subtype")) or "")
        self.base = str(r(self.d.get("BaseFont")) or "")
        low = self.base.lower().split("+")[-1]
        self.courier = "courier" in low or "mono" in low or "consolas" in low
        self.bold = "bold" in low or "black" in low
        self.bullet_table = next((t for k, t in _BULLET_FONTS.items() if k in low), None)
        self.composite = self.subtype == "Type0"
        self.to_unicode = None
        self.cmap_in = None          # code -> cid for composite fonts with their own CMap
        self.widths = {}
        self.default_width = 1000 if self.composite else 0
        self.first_char = 0
        self.table = [None] * 256
        self.unmapped = 0
        self.mapped = 0
        self._load()

    # -- loading
    def _load(self):
        r = self.pdf.resolve
        tu = r(self.d.get("ToUnicode"))
        if isinstance(tu, Stream):
            try:
                self.to_unicode = CMap().parse(decode_stream(tu))
            except PdfError:
                self.to_unicode = None
        if self.composite:
            self._load_composite()
        else:
            self._load_simple()

    def _load_composite(self):
        r = self.pdf.resolve
        enc = r(self.d.get("Encoding"))
        if isinstance(enc, Stream):
            try:
                self.cmap_in = CMap().parse(decode_stream(enc))
            except PdfError:
                self.cmap_in = None
        elif isinstance(enc, str) and enc not in ("Identity-H", "Identity-V"):
            self.cmap_in = None  # a predefined CMap: codes are 2 bytes; ToUnicode does the work
        desc = r(self.d.get("DescendantFonts"))
        df = r(desc[0]) if isinstance(desc, list) and desc else {}
        if isinstance(df, dict):
            dw = r(df.get("DW"))
            self.default_width = float(dw) if isinstance(dw, (int, float)) else 1000
            w = r(df.get("W"))
            if isinstance(w, list):
                self._parse_w(w)

    def _parse_w(self, w):
        r = self.pdf.resolve
        i = 0
        n = len(w)
        while i < n:
            first = r(w[i])
            if i + 1 >= n or not isinstance(first, int):
                break
            second = r(w[i + 1])
            if isinstance(second, list):
                for k, width in enumerate(second):
                    width = r(width)
                    if isinstance(width, (int, float)):
                        self.widths[first + k] = float(width)
                i += 2
            elif i + 2 < n and isinstance(second, int):
                width = r(w[i + 2])
                if isinstance(width, (int, float)) and second - first < 70000:
                    for c in range(first, second + 1):
                        self.widths[c] = float(width)
                i += 3
            else:
                break

    def _load_simple(self):
        r = self.pdf.resolve
        enc = r(self.d.get("Encoding"))
        base_name = None
        diffs = None
        if isinstance(enc, str):
            base_name = str(enc)
        elif isinstance(enc, dict):
            be = r(enc.get("BaseEncoding"))
            base_name = str(be) if be else None
            diffs = r(enc.get("Differences"))
        base = _BASE.get(base_name)
        if base is None:
            # no encoding given: Standard for Type1, WinAnsi for TrueType (what readers do in practice)
            base = _BASE["StandardEncoding"] if self.subtype in ("Type1", "MMType1", "Type3") else _BASE["WinAnsiEncoding"]
            if self.subtype in ("Type1", "MMType1") and not self.base.startswith(("Helvetica", "Times", "Courier", "Arial")):
                base = _BASE["WinAnsiEncoding"] if self.to_unicode is None else base
        self.table = list(base)
        if isinstance(diffs, list):
            code = 0
            for item in diffs:
                item = r(item)
                if isinstance(item, int):
                    code = item
                elif isinstance(item, str):
                    if 0 <= code < 256:
                        ch = glyph_char(str(item))
                        self.table[code] = ch
                    code += 1
        fc = r(self.d.get("FirstChar"))
        self.first_char = fc if isinstance(fc, int) else 0
        widths = r(self.d.get("Widths"))
        if isinstance(widths, list):
            for k, wv in enumerate(widths[:256]):
                wv = r(wv)
                if isinstance(wv, (int, float)):
                    self.widths[self.first_char + k] = float(wv)
        desc = r(self.d.get("FontDescriptor"))
        if isinstance(desc, dict):
            mw = r(desc.get("MissingWidth"))
            if isinstance(mw, (int, float)):
                self.default_width = float(mw)
        if self.subtype == "Type3":
            fm = r(self.d.get("FontMatrix"))
            scale = float(r(fm[0])) * 1000 if isinstance(fm, list) and fm and isinstance(r(fm[0]), (int, float)) else 1.0
            self.widths = {k: v * scale for k, v in self.widths.items()}

    # -- using
    def decode(self, data):
        """List of (text, width in 1/1000 em, is_single_byte_space)."""
        out = []
        if self.composite:
            cm = self.cmap_in
            codes = cm.split(data) if cm is not None and cm.space else \
                [int.from_bytes(data[i:i + 2], "big") for i in range(0, len(data) - 1, 2)] + ([data[-1]] if len(data) % 2 else [])
            for code in codes:
                cid = code
                if cm is not None:
                    c2 = cm.to_cid(code)
                    if c2 is not None:
                        cid = c2
                text = self.to_unicode.to_unicode(code) if self.to_unicode else None
                if text is None:
                    text = self._composite_fallback(code)
                self._count(text)
                out.append((text, self.widths.get(cid, self.default_width), False))
            return out
        for code in data:
            text = None
            if self.to_unicode:
                text = self.to_unicode.to_unicode(code)
            if text is None and self.bullet_table and code in self.bullet_table and not self.to_unicode:
                text = self.bullet_table[code]
            if text is None:
                text = self.table[code] if code < 256 else None
            if text is None and self.to_unicode and 32 <= code < 127:
                text = chr(code)
            if text is None and self.table[code] is None and 32 <= code < 127:
                text = chr(code)
            if text is None:
                text = UNKNOWN if code >= 32 else ""
            self._count(text)
            width = self.widths.get(code)
            if width is None:
                if self.default_width:
                    width = self.default_width
                else:
                    width = _approx_width(text[:1] or " ", self.courier, self.bold)
            out.append((text, width, code == 32))
        return out

    def _composite_fallback(self, code):
        # No ToUnicode: the codes are glyph numbers of the embedded font, which we cannot read.
        return UNKNOWN

    def _count(self, text):
        if UNKNOWN in text:
            self.unmapped += 1
        elif text.strip():
            self.mapped += 1
