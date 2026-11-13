"""Our own PDF reader, part 1: the file structure.

Pure Python, standard library only. This file knows how a PDF is built (objects, the cross-reference
table, compressed object streams, stream filters, the page tree). `pdffonts.py` knows fonts and
`pdftext.py` turns a page into text with positions.

Safety: every loop has a limit, every recursion has a depth, decompression has a size cap, and every
failure is a `PdfError` (never a crash). Encrypted files are refused with `PdfEncrypted`.
"""

import re
import zlib

MAX_STREAM_BYTES = 40 * 1024 * 1024       # one decompressed stream
MAX_TOTAL_BYTES = 120 * 1024 * 1024        # everything decompressed for one document
MAX_OBJECTS = 200_000
MAX_DEPTH = 60
MAX_PAGES_WALKED = 500

_WS = b"\x00\t\n\x0c\r "
_DELIM = b"()<>[]{}/%"
_REGULAR_END = re.compile(rb"[\x00\t\n\x0c\r ()<>\[\]{}/%]")
_NUMBER = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)")
_OBJ_HEADER = re.compile(rb"(?<![\d.])(\d{1,10})\s+(\d{1,5})\s+obj\b")


class PdfError(ValueError):
    """The PDF cannot be read."""


class PdfEncrypted(PdfError):
    """The PDF is encrypted (password protected)."""


class Name(str):
    """A PDF name such as /Type."""
    __slots__ = ()


class Op(str):
    """A bare keyword in a content stream, such as BT or Tj."""
    __slots__ = ()


class Ref(tuple):
    """An indirect reference "12 0 R"."""
    __slots__ = ()

    def __new__(cls, num, gen=0):
        return tuple.__new__(cls, (num, gen))

    @property
    def num(self):
        return self[0]


class Stream:
    """A dictionary plus raw (still encoded) bytes."""
    __slots__ = ("dict", "raw", "pdf")

    def __init__(self, d, raw, pdf):
        self.dict = d
        self.raw = raw
        self.pdf = pdf

    def get(self, key, default=None):
        return self.pdf.resolve(self.dict.get(key, default))


# ---------------------------------------------------------------- lexer

class Lexer:
    """Reads PDF syntax from bytes. Used for the file and for content streams."""

    def __init__(self, data, pos=0, refs=True):
        self.data = data
        self.pos = pos
        self.refs = refs  # recognise "12 0 R"

    def skip_ws(self):
        data, n, pos = self.data, len(self.data), self.pos
        while pos < n:
            c = data[pos]
            if c in _WS:
                pos += 1
            elif c == 0x25:  # % comment
                while pos < n and data[pos] not in b"\r\n":
                    pos += 1
            else:
                break
        self.pos = pos

    def at_end(self):
        self.skip_ws()
        return self.pos >= len(self.data)

    def read(self, depth=0):
        """Next object. Bare keywords come back as `Op`."""
        if depth > MAX_DEPTH:
            raise PdfError("nesting too deep")
        self.skip_ws()
        data, pos = self.data, self.pos
        if pos >= len(data):
            raise PdfError("unexpected end")
        c = data[pos]
        if c == 0x2F:  # /
            return self._name()
        if c == 0x28:  # (
            return self._literal_string()
        if c == 0x3C:  # <
            if data[pos + 1:pos + 2] == b"<":
                return self._dict(depth)
            return self._hex_string()
        if c == 0x5B:  # [
            self.pos += 1
            items = []
            while True:
                self.skip_ws()
                if self.pos >= len(data):
                    raise PdfError("unterminated array")
                if data[self.pos] == 0x5D:
                    self.pos += 1
                    return items
                items.append(self.read(depth + 1))
        if c in b"+-.0123456789":
            return self._number_or_ref()
        if c in b")>]}{":
            self.pos += 1  # stray delimiter: skip it, return a harmless operator
            return Op(chr(c))
        m = _REGULAR_END.search(data, pos)
        end = m.start() if m else len(data)
        if end == pos:
            end = pos + 1
        word = data[pos:end]
        self.pos = end
        if word == b"true":
            return True
        if word == b"false":
            return False
        if word == b"null":
            return None
        return Op(word.decode("latin-1"))

    def _name(self):
        data = self.data
        m = _REGULAR_END.search(data, self.pos + 1)
        end = m.start() if m else len(data)
        raw = data[self.pos + 1:end]
        self.pos = end
        if b"#" in raw:
            raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda mm: bytes([int(mm.group(1), 16)]), raw)
        return Name(raw.decode("utf-8", "replace") if raw else "")

    def _number_or_ref(self):
        data = self.data
        m = _NUMBER.match(data, self.pos)
        if not m:
            # things like "--5" or "-" : take the sign characters and carry on
            self.pos += 1
            return 0
        text = m.group()
        end = m.end()
        if data[end:end + 1] and data[end:end + 1] not in _WS + _DELIM:
            # a number glued to letters (e.g. "12Tj") : take the number only
            pass
        is_int = b"." not in text
        value = int(text) if is_int else float(text)
        if self.refs and is_int and value >= 0:
            m2 = re.compile(rb"[ \t\r\n\x0c\x00]+(\d{1,5})[ \t\r\n\x0c\x00]+R(?![A-Za-z0-9])").match(data, end)
            if m2:
                self.pos = m2.end()
                return Ref(value, int(m2.group(1)))
        self.pos = end
        return value

    def _literal_string(self):
        data, pos, n = self.data, self.pos + 1, len(self.data)
        out = bytearray()
        depth = 1
        while pos < n:
            c = data[pos]
            if c == 0x5C:  # backslash
                pos += 1
                if pos >= n:
                    break
                e = data[pos]
                simple = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12, 0x28: 40, 0x29: 41, 0x5C: 92}
                if e in simple:
                    out.append(simple[e])
                    pos += 1
                elif 0x30 <= e <= 0x37:
                    digits = chr(e)
                    pos += 1
                    for _ in range(2):
                        if pos < n and 0x30 <= data[pos] <= 0x37:
                            digits += chr(data[pos])
                            pos += 1
                        else:
                            break
                    out.append(int(digits, 8) & 0xFF)
                elif e == 0x0D:  # line continuation
                    pos += 1
                    if data[pos:pos + 1] == b"\n":
                        pos += 1
                elif e == 0x0A:
                    pos += 1
                else:
                    out.append(e)
                    pos += 1
                continue
            if c == 0x28:
                depth += 1
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    pos += 1
                    break
            out.append(c)
            pos += 1
        self.pos = pos
        return bytes(out)

    def _hex_string(self):
        data = self.data
        end = data.find(b">", self.pos)
        if end < 0:
            end = len(data)
        digits = re.sub(rb"[^0-9A-Fa-f]", b"", data[self.pos + 1:end])
        if len(digits) % 2:
            digits += b"0"
        self.pos = min(end + 1, len(data))
        return bytes.fromhex(digits.decode("ascii"))

    def _dict(self, depth):
        self.pos += 2
        d = {}
        data = self.data
        while True:
            self.skip_ws()
            if self.pos >= len(data):
                raise PdfError("unterminated dictionary")
            if data[self.pos:self.pos + 2] == b">>":
                self.pos += 2
                return d
            key = self.read(depth + 1)
            if not isinstance(key, Name):
                continue  # junk: skip it
            self.skip_ws()
            if data[self.pos:self.pos + 2] == b">>":
                d[str(key)] = None
                self.pos += 2
                return d
            d[str(key)] = self.read(depth + 1)


# ---------------------------------------------------------------- stream filters

def _flate(data, params):
    out = bytearray()
    d = zlib.decompressobj()
    try:
        chunk = d.decompress(data, MAX_STREAM_BYTES)
        out += chunk
        if d.unconsumed_tail:
            raise PdfError("a stream is too large")
    except zlib.error:
        # damaged or cut-off data: keep what could be read; try raw deflate if nothing came out
        if not out:
            try:
                d2 = zlib.decompressobj(-15)
                out += d2.decompress(data[2:], MAX_STREAM_BYTES)
            except zlib.error:
                out = bytearray(_salvage_flate(data))
    return _predictor(bytes(out), params)


def _salvage_flate(data):
    d = zlib.decompressobj()
    out = bytearray()
    for i in range(0, len(data), 256):
        try:
            out += d.decompress(data[i:i + 256])
        except zlib.error:
            break
        if len(out) > MAX_STREAM_BYTES:
            raise PdfError("a stream is too large")
    return out


def _lzw_decode(data, early=1):
    out = bytearray()
    table = [bytes([i]) for i in range(256)] + [b"", b""]
    code_len = 9
    prev = None
    buf = 0
    nbits = 0
    for byte in data:
        buf = (buf << 8) | byte
        nbits += 8
        while nbits >= code_len:
            code = (buf >> (nbits - code_len)) & ((1 << code_len) - 1)
            nbits -= code_len
            buf &= (1 << nbits) - 1
            if code == 256:
                table = table[:258]
                code_len = 9
                prev = None
                continue
            if code == 257:
                return bytes(out)
            if prev is None:
                if code >= len(table):
                    return bytes(out)
                entry = table[code]
            else:
                if code < len(table):
                    entry = table[code]
                elif code == len(table):
                    entry = prev + prev[:1]
                else:
                    return bytes(out)
                table.append(prev + entry[:1])
            out += entry
            if len(out) > MAX_STREAM_BYTES:
                raise PdfError("a stream is too large")
            prev = entry
            size = len(table) + early
            code_len = 9 if size < 512 else 10 if size < 1024 else 11 if size < 2048 else 12
    return bytes(out)


def _ascii85(data):
    data = data.strip()
    if data.startswith(b"<~"):
        data = data[2:]
    end = data.find(b"~>")
    if end >= 0:
        data = data[:end]
    out = bytearray()
    group = []
    for c in data:
        if c in _WS:
            continue
        if c == 0x7A and not group:  # z = four zero bytes
            out += b"\x00\x00\x00\x00"
            continue
        if not 0x21 <= c <= 0x75:
            continue
        group.append(c - 33)
        if len(group) == 5:
            v = 0
            for g in group:
                v = v * 85 + g
            out += (v & 0xFFFFFFFF).to_bytes(4, "big")
            group = []
    if len(group) > 1:
        n = len(group)
        group += [84] * (5 - n)
        v = 0
        for g in group:
            v = v * 85 + g
        out += (v & 0xFFFFFFFF).to_bytes(4, "big")[:n - 1]
    return bytes(out)


def _asciihex(data):
    end = data.find(b">")
    if end >= 0:
        data = data[:end]
    digits = re.sub(rb"[^0-9A-Fa-f]", b"", data)
    if len(digits) % 2:
        digits += b"0"
    return bytes.fromhex(digits.decode("ascii"))


def _runlength(data):
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        length = data[i]
        i += 1
        if length == 128:
            break
        if length < 128:
            out += data[i:i + length + 1]
            i += length + 1
        else:
            if i < n:
                out += data[i:i + 1] * (257 - length)
            i += 1
        if len(out) > MAX_STREAM_BYTES:
            raise PdfError("a stream is too large")
    return bytes(out)


def _predictor(data, params):
    if not params:
        return data
    predictor = int(params.get("Predictor", 1) or 1)
    if predictor < 2:
        return data
    colors = int(params.get("Colors", 1) or 1)
    bpc = int(params.get("BitsPerComponent", 8) or 8)
    columns = int(params.get("Columns", 1) or 1)
    bpp = max(1, (colors * bpc + 7) // 8)
    stride = (colors * bpc * columns + 7) // 8
    if stride <= 0 or stride > 20_000_000 or colors > 64 or bpc > 16:
        return data
    if predictor == 2:  # TIFF predictor, 8 bits per component only
        if bpc != 8:
            return data
        out = bytearray(data)
        for row in range(0, len(out) - stride + 1, stride):
            for i in range(row + colors, row + stride):
                out[i] = (out[i] + out[i - colors]) & 0xFF
        return bytes(out)
    # PNG predictors: each row starts with its own filter byte
    out = bytearray()
    prev = bytearray(stride)
    pos = 0
    n = len(data)
    while pos < n:
        ft = data[pos]
        row = bytearray(data[pos + 1:pos + 1 + stride])
        if len(row) < stride:
            row += bytes(stride - len(row))
        pos += 1 + stride
        if ft == 1:
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif ft == 2:
            row = bytearray(((a + b) & 0xFF) for a, b in zip(row, prev))
        elif ft == 3:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                row[i] = (row[i] + pred) & 0xFF
        out += row
        prev = row
        if len(out) > MAX_STREAM_BYTES:
            raise PdfError("a stream is too large")
    return bytes(out)


IMAGE_FILTERS = ("DCTDecode", "DCT", "JPXDecode", "CCITTFaxDecode", "CCF", "JBIG2Decode")
_ALIASES = {"Fl": "FlateDecode", "LZW": "LZWDecode", "A85": "ASCII85Decode", "AHx": "ASCIIHexDecode",
            "RL": "RunLengthDecode", "DCT": "DCTDecode", "CCF": "CCITTFaxDecode"}


def filters_of(stream_dict, pdf):
    """List of (filter name, decode params dict)."""
    f = pdf.resolve(stream_dict.get("Filter", stream_dict.get("F")))
    p = pdf.resolve(stream_dict.get("DecodeParms", stream_dict.get("DP")))
    if f is None:
        return []
    if not isinstance(f, list):
        f = [f]
        p = [p]
    elif not isinstance(p, list):
        p = [p] * len(f)
    out = []
    for i, name in enumerate(f):
        name = pdf.resolve(name)
        params = pdf.resolve(p[i]) if i < len(p) else None
        if isinstance(params, dict):
            params = {k: pdf.resolve(v) for k, v in params.items()}
        else:
            params = None
        out.append((_ALIASES.get(str(name), str(name)), params))
    return out


def decode_stream(stream, stop_at_image=False):
    """Decoded bytes. With stop_at_image=True returns (bytes, remaining_filters) and leaves image codecs alone."""
    pdf = stream.pdf
    data = stream.raw
    chain = filters_of(stream.dict, pdf)
    for i, (name, params) in enumerate(chain):
        if name in IMAGE_FILTERS:
            if stop_at_image:
                return data, chain[i:]
            raise PdfError("image data is not text")
        pdf._budget(len(data))
        if name == "FlateDecode":
            data = _flate(data, params)
        elif name == "LZWDecode":
            data = _predictor(_lzw_decode(data, int((params or {}).get("EarlyChange", 1))), params)
        elif name == "ASCII85Decode":
            data = _ascii85(data)
        elif name == "ASCIIHexDecode":
            data = _asciihex(data)
        elif name == "RunLengthDecode":
            data = _runlength(data)
        elif name == "Crypt":
            continue
        else:
            raise PdfError("unsupported stream filter " + name)
    return (data, []) if stop_at_image else data


# ---------------------------------------------------------------- the document

class Pdf:
    def __init__(self, data):
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise PdfError("empty file")
        self.data = bytes(data)
        self.xref = {}       # object number -> ("n", offset) or ("c", stream object number, index)
        self.trailer = {}
        self._cache = {}
        self._objstm = {}
        self._total = 0
        self._rebuilt = False
        self._loading = set()
        head = self.data[:1024]
        if b"%PDF-" not in head:
            raise PdfError("not a PDF")
        try:
            self._read_xref_chain()
            if not isinstance(self.resolve(self.trailer.get("Root")), dict):
                raise PdfError("no catalog")
        except PdfEncrypted:
            raise
        except (PdfError, ValueError, KeyError, IndexError, TypeError, RecursionError):
            self._rebuild()
        if self.trailer.get("Encrypt") is not None:
            raise PdfEncrypted("the PDF is password protected")
        if not isinstance(self.resolve(self.trailer.get("Root")), dict):
            raise PdfError("the PDF has no pages")

    # -- limits
    def _budget(self, n):
        self._total += n
        if self._total > MAX_TOTAL_BYTES:
            raise PdfError("the PDF is too large to read")

    # -- reading the cross-reference data
    def _read_xref_chain(self):
        tail = self.data[-4096:]
        i = tail.rfind(b"startxref")
        if i < 0:
            raise PdfError("no startxref")
        m = re.match(rb"startxref\s+(\d+)", tail[i:])
        if not m:
            raise PdfError("bad startxref")
        offset = int(m.group(1))
        seen = set()
        first = True
        while offset is not None:
            if offset in seen or offset < 0 or offset >= len(self.data):
                break
            seen.add(offset)
            trailer = self._read_xref_at(offset)
            if first:
                self.trailer = dict(trailer)
                first = False
            else:
                for k, v in trailer.items():
                    self.trailer.setdefault(k, v)
            xs = trailer.get("XRefStm")
            if isinstance(xs, int) and xs not in seen:
                seen.add(xs)
                try:
                    self._read_xref_at(xs)
                except PdfError:
                    pass
            prev = trailer.get("Prev")
            offset = int(prev) if isinstance(prev, (int, float)) else None
        if "Encrypt" in self.trailer:
            raise PdfEncrypted("the PDF is password protected")
        if not self.xref:
            raise PdfError("empty cross-reference")

    def _read_xref_at(self, offset):
        data = self.data
        lex = Lexer(data, offset)
        lex.skip_ws()
        if data[lex.pos:lex.pos + 4] == b"xref":
            lex.pos += 4
            while True:
                lex.skip_ws()
                if data[lex.pos:lex.pos + 7] == b"trailer":
                    lex.pos += 7
                    trailer = lex.read()
                    if not isinstance(trailer, dict):
                        raise PdfError("bad trailer")
                    return trailer
                start = lex.read()
                count = lex.read()
                if not isinstance(start, int) or not isinstance(count, int):
                    raise PdfError("bad xref subsection")
                for k in range(count):
                    off = lex.read()
                    gen = lex.read()
                    kind = lex.read()
                    if not isinstance(off, int) or str(kind) not in ("n", "f"):
                        raise PdfError("bad xref entry")
                    num = start + k
                    if str(kind) == "n" and off > 0 and num not in self.xref:
                        self.xref[num] = ("n", off)
                    elif str(kind) == "f":
                        self.xref.setdefault(num, ("f", 0))
        # cross-reference stream
        obj = self._parse_indirect_at(offset)
        if not isinstance(obj, Stream) or obj.dict.get("Type") != "XRef":
            raise PdfError("no cross-reference at offset")
        body = decode_stream(obj)
        w = [int(x) for x in self.resolve(obj.dict.get("W"))]
        if len(w) != 3 or any(x < 0 or x > 8 for x in w):
            raise PdfError("bad xref widths")
        size = int(obj.dict.get("Size", 0))
        index = obj.dict.get("Index") or [0, size]
        row = sum(w)
        pos = 0
        for s in range(0, len(index) - 1, 2):
            start, count = int(index[s]), int(index[s + 1])
            for k in range(count):
                if pos + row > len(body):
                    break
                fields = []
                p = pos
                for width in w:
                    fields.append(int.from_bytes(body[p:p + width], "big") if width else None)
                    p += width
                pos += row
                kind = 1 if fields[0] is None else fields[0]
                num = start + k
                if num in self.xref:
                    continue
                if kind == 1:
                    self.xref[num] = ("n", fields[1] or 0)
                elif kind == 2:
                    self.xref[num] = ("c", fields[1] or 0, fields[2] or 0)
                else:
                    self.xref[num] = ("f", 0)
        return obj.dict

    def _rebuild(self):
        """The cross-reference data is missing or wrong: find every "N G obj" in the file."""
        if self._rebuilt:
            raise PdfError("the PDF structure is damaged")
        self._rebuilt = True
        self.xref = {}
        self._cache = {}
        self._objstm = {}
        data = self.data
        count = 0
        for m in _OBJ_HEADER.finditer(data):
            count += 1
            if count > MAX_OBJECTS:
                raise PdfError("too many objects")
            self.xref[int(m.group(1))] = ("n", m.start())
        trailer = {}
        for m in re.finditer(rb"trailer", data):
            try:
                t = Lexer(data, m.end()).read()
            except PdfError:
                continue
            if isinstance(t, dict):
                for k, v in t.items():
                    trailer[k] = v
        # object streams and cross-reference streams
        for num in sorted(self.xref):
            ent = self.xref[num]
            if ent[0] != "n":
                continue
            window = data[ent[1]:ent[1] + 400]
            if b"/ObjStm" in window or b"/XRef" in window:
                try:
                    obj = self._parse_indirect_at(ent[1])
                except PdfError:
                    continue
                if isinstance(obj, Stream):
                    typ = obj.dict.get("Type")
                    if typ == "XRef":
                        for k, v in obj.dict.items():
                            trailer.setdefault(k, v)
                    elif typ == "ObjStm":
                        try:
                            n = int(obj.dict.get("N", 0))
                            body = decode_stream(obj)
                            lex = Lexer(body, 0, refs=False)
                            for idx in range(n):
                                onum = lex.read()
                                lex.read()
                                if isinstance(onum, int) and onum not in self.xref:
                                    self.xref[onum] = ("c", num, idx)
                        except (PdfError, ValueError, TypeError):
                            continue
        if not isinstance(self.resolve(trailer.get("Root")), dict):
            for num in sorted(self.xref):
                try:
                    obj = self.get(num)
                except PdfError:
                    continue
                if isinstance(obj, dict) and obj.get("Type") == "Catalog":
                    trailer["Root"] = Ref(num, 0)
        self.trailer = trailer
        if trailer.get("Encrypt") is not None:
            raise PdfEncrypted("the PDF is password protected")

    # -- objects
    def _parse_indirect_at(self, offset, expect=None):
        data = self.data
        lex = Lexer(data, offset)
        num = lex.read()
        gen = lex.read()
        kw = lex.read()
        if not (isinstance(num, int) and isinstance(gen, int) and isinstance(kw, Op) and kw == "obj"):
            raise PdfError("no object at offset")
        if expect is not None and num != expect:
            raise PdfError("wrong object at offset")
        obj = lex.read()
        if isinstance(obj, dict):
            lex.skip_ws()
            if data[lex.pos:lex.pos + 6] == b"stream":
                start = lex.pos + 6
                if data[start:start + 2] == b"\r\n":
                    start += 2
                elif data[start:start + 1] in (b"\n", b"\r"):
                    start += 1
                length = obj.get("Length")
                length = self.resolve(length) if isinstance(length, Ref) else length
                end = None
                if isinstance(length, int) and 0 <= length <= len(data) - start:
                    tail = data[start + length:start + length + 20].lstrip(_WS)
                    if tail.startswith(b"endstream"):
                        end = start + length
                if end is None:
                    e = data.find(b"endstream", start)
                    if e < 0:
                        e = len(data)
                    end = e
                    if data[end - 2:end] == b"\r\n":
                        end -= 2
                    elif data[end - 1:end] in (b"\n", b"\r"):
                        end -= 1
                obj = Stream(obj, data[start:end], self)
        return obj

    def get(self, num):
        if num in self._cache:
            return self._cache[num]
        ent = self.xref.get(num)
        if ent is None or ent[0] == "f":
            return None
        if num in self._loading:
            return None
        self._loading.add(num)
        try:
            if ent[0] == "n":
                try:
                    obj = self._parse_indirect_at(ent[1], expect=num)
                except PdfError:
                    if not self._rebuilt:
                        self._rebuild()
                        return self.get(num)
                    obj = None
            else:
                obj = self._from_objstm(ent[1], ent[2], num)
        finally:
            self._loading.discard(num)
        self._cache[num] = obj
        return obj

    def _from_objstm(self, stm_num, index, num):
        if stm_num not in self._objstm:
            stm = self.get(stm_num)
            if not isinstance(stm, Stream):
                return None
            body = decode_stream(stm)
            n = int(self.resolve(stm.dict.get("N", 0)))
            first = int(self.resolve(stm.dict.get("First", 0)))
            lex = Lexer(body, 0, refs=False)
            pairs = []
            for _ in range(min(n, MAX_OBJECTS)):
                a = lex.read()
                b = lex.read()
                if not isinstance(a, int) or not isinstance(b, int):
                    break
                pairs.append((a, b))
            self._objstm[stm_num] = (body, first, pairs)
        body, first, pairs = self._objstm[stm_num]
        for onum, off in pairs:
            if onum == num:
                return Lexer(body, first + off).read()
        return None

    def resolve(self, obj):
        for _ in range(30):
            if isinstance(obj, Ref):
                obj = self.get(obj.num)
            else:
                return obj
        return None

    # -- pages
    def catalog(self):
        root = self.resolve(self.trailer.get("Root"))
        if not isinstance(root, dict):
            raise PdfError("the PDF has no catalog")
        return root

    def pages(self, limit=MAX_PAGES_WALKED):
        """Page dictionaries (copies with inherited attributes filled in)."""
        root = self.catalog()
        out = []
        seen = set()
        inherit_keys = ("Resources", "MediaBox", "CropBox", "Rotate")

        def walk(node_ref, inherited, depth):
            if depth > 40 or len(out) >= limit:
                return
            key = node_ref.num if isinstance(node_ref, Ref) else id(node_ref)
            if key in seen:
                return
            seen.add(key)
            node = self.resolve(node_ref)
            if not isinstance(node, dict):
                return
            inh = dict(inherited)
            for k in inherit_keys:
                if k in node:
                    inh[k] = node[k]
            kids = self.resolve(node.get("Kids"))
            if node.get("Type") == "Pages" or (isinstance(kids, list) and node.get("Type") != "Page"):
                for kid in (kids or []):
                    walk(kid, inh, depth + 1)
            else:
                page = dict(node)
                for k, v in inh.items():
                    page.setdefault(k, v)
                out.append(page)

        walk(root.get("Pages"), {}, 0)
        if not out:
            # damaged page tree: look for page objects directly
            for num in sorted(self.xref):
                o = self.get(num)
                if isinstance(o, dict) and o.get("Type") == "Page":
                    out.append(dict(o))
                    if len(out) >= limit:
                        break
        return out

    def page_count(self):
        try:
            top = self.resolve(self.catalog().get("Pages"))
            n = self.resolve(top.get("Count")) if isinstance(top, dict) else None
            if isinstance(n, int) and 0 <= n <= MAX_PAGES_WALKED:
                return n
        except PdfError:
            pass
        return len(self.pages())

    def content_bytes(self, page):
        """All content streams of a page joined together."""
        c = self.resolve(page.get("Contents"))
        parts = c if isinstance(c, list) else [c]
        out = []
        for p in parts:
            p = self.resolve(p)
            if isinstance(p, Stream):
                try:
                    out.append(decode_stream(p))
                except PdfError:
                    continue
        return b"\n".join(out)
