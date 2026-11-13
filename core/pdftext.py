"""Our own PDF reader, part 3: text with positions, and reading order.

`read_page` runs the page's drawing instructions and records every piece of text with its place on the
page. `layout` then does what a reader's eyes do: group pieces into lines, notice two-column pages (a
Canva sidebar, a LinkedIn export) and read one column after the other instead of mixing them.
"""

import math
import statistics

from .pdffonts import Font, PRIVATE_USE_BULLETS
from .pdfread import Lexer, Name, Op, PdfError, Ref, Stream, decode_stream

MAX_OPERATIONS = 1_500_000
MAX_FORM_DEPTH = 6
MAX_CHUNKS = 60_000

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mul(m, n):
    """Apply m first, then n."""
    return (
        m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3],
        m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3],
        m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5],
    )


class Chunk:
    __slots__ = ("x0", "x1", "y", "size", "text")

    def __init__(self, x0, x1, y, size, text):
        self.x0, self.x1, self.y, self.size, self.text = x0, x1, y, size, text


class PageData:
    def __init__(self):
        self.chunks = []
        self.images = []      # (stream, fraction of the page covered)
        self.width = 612.0
        self.height = 792.0
        self.mapped = 0
        self.unmapped = 0
        self.rotate = 0


def _num(x, default=0.0):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else default


def _box(pdf, page):
    box = pdf.resolve(page.get("CropBox")) or pdf.resolve(page.get("MediaBox"))
    if isinstance(box, list) and len(box) == 4:
        v = [_num(pdf.resolve(b)) for b in box]
        x0, x1 = sorted((v[0], v[2]))
        y0, y1 = sorted((v[1], v[3]))
        if x1 - x0 > 10 and y1 - y0 > 10:
            return x0, y0, x1, y1
    return 0.0, 0.0, 612.0, 792.0


class _Reader:
    def __init__(self, pdf, page_data):
        self.pdf = pdf
        self.out = page_data
        self.fonts = {}
        self.ops = 0

    def font(self, res, name):
        fonts = self.pdf.resolve(res.get("Font")) if isinstance(res, dict) else None
        if not isinstance(fonts, dict):
            return None
        ref = fonts.get(name)
        key = ref.num if isinstance(ref, Ref) else id(ref)
        if key not in self.fonts:
            fd = self.pdf.resolve(ref)
            try:
                self.fonts[key] = Font(self.pdf, fd) if isinstance(fd, dict) else None
            except (PdfError, ValueError, KeyError, TypeError, RecursionError):
                self.fonts[key] = None
        return self.fonts[key]

    def run(self, content, res, ctm, depth=0):
        pdf = self.pdf
        lex = Lexer(content, 0, refs=False)
        stack = []
        gstack = []
        font = None
        fsize = 0.0
        tc = tw = trise = 0.0
        th = 1.0
        tl = 0.0
        tm = tlm = IDENTITY
        chunk_parts = []
        out = self.out

        def show(parts):
            """parts: list of bytes or numbers (TJ array). Emits chunks."""
            nonlocal tm
            if font is None:
                return
            pieces = []
            start = None
            size = 0.0
            for item in parts:
                if isinstance(item, (bytes, bytearray)):
                    for text, width, is_space in font.decode(bytes(item)):
                        if start is None:
                            trm = mul(tm, ctm)
                            start = (trm[4], trm[5])
                            size = fsize * math.hypot(trm[2], trm[3])
                        pieces.append(text)
                        tx = (width / 1000.0 * fsize + tc + (tw if is_space else 0.0)) * th
                        tm = mul((1, 0, 0, 1, tx, 0), tm)
                elif isinstance(item, (int, float)):
                    if start is None:
                        continue
                    tm = mul((1, 0, 0, 1, -item / 1000.0 * fsize * th, 0), tm)
                    if item < -160 and pieces and not pieces[-1].endswith(" "):
                        pieces.append(" ")
                    if item < -1500:  # a tab or a jump to another column: start a new piece
                        flush(pieces, start, size)
                        pieces, start = [], None
            flush(pieces, start, size)

        def flush(pieces, start, size):
            if start is None or not pieces:
                return
            text = "".join(pieces)
            if not text.strip():
                return
            trm = mul(tm, ctm)
            if len(out.chunks) < MAX_CHUNKS:
                out.chunks.append(Chunk(start[0], trm[4], start[1], max(size, 1.0), text))

        while True:
            try:
                if lex.at_end():
                    break
                tok = lex.read()
            except PdfError:
                break
            if not isinstance(tok, Op):
                stack.append(tok)
                if len(stack) > 512:
                    del stack[:256]
                continue
            self.ops += 1
            if self.ops > MAX_OPERATIONS:
                break
            op = str(tok)
            try:
                if op == "q":
                    gstack.append((ctm, font, fsize, tc, tw, th, tl, trise))
                elif op == "Q":
                    if gstack:
                        ctm, font, fsize, tc, tw, th, tl, trise = gstack.pop()
                elif op == "cm":
                    if len(stack) >= 6:
                        ctm = mul(tuple(_num(v) for v in stack[-6:]), ctm)
                elif op == "BT":
                    tm = tlm = IDENTITY
                elif op == "Tf":
                    if len(stack) >= 2:
                        font = self.font(res, str(stack[-2])) if isinstance(stack[-2], Name) else font
                        fsize = _num(stack[-1], fsize)
                elif op == "Tc":
                    tc = _num(stack[-1]) if stack else tc
                elif op == "Tw":
                    tw = _num(stack[-1]) if stack else tw
                elif op == "Tz":
                    th = _num(stack[-1], 100.0) / 100.0 if stack else th
                elif op == "TL":
                    tl = _num(stack[-1]) if stack else tl
                elif op == "Ts":
                    trise = _num(stack[-1]) if stack else trise
                elif op in ("Td", "TD"):
                    if len(stack) >= 2:
                        tx, ty = _num(stack[-2]), _num(stack[-1])
                        if op == "TD":
                            tl = -ty
                        tlm = mul((1, 0, 0, 1, tx, ty), tlm)
                        tm = tlm
                elif op == "Tm":
                    if len(stack) >= 6:
                        tm = tlm = tuple(_num(v) for v in stack[-6:])
                elif op == "T*":
                    tlm = mul((1, 0, 0, 1, 0, -tl), tlm)
                    tm = tlm
                elif op == "Tj":
                    if stack and isinstance(stack[-1], (bytes, bytearray)):
                        show([stack[-1]])
                elif op == "TJ":
                    if stack and isinstance(stack[-1], list):
                        show(stack[-1])
                elif op == "'":
                    tlm = mul((1, 0, 0, 1, 0, -tl), tlm)
                    tm = tlm
                    if stack and isinstance(stack[-1], (bytes, bytearray)):
                        show([stack[-1]])
                elif op == '"':
                    if len(stack) >= 3:
                        tw, tc = _num(stack[-3]), _num(stack[-2])
                    tlm = mul((1, 0, 0, 1, 0, -tl), tlm)
                    tm = tlm
                    if stack and isinstance(stack[-1], (bytes, bytearray)):
                        show([stack[-1]])
                elif op == "Do":
                    if stack and isinstance(stack[-1], Name):
                        self._do(res, str(stack[-1]), ctm, depth)
                elif op == "BI":
                    self._inline_image(lex, ctm)
            except (PdfError, ValueError, TypeError, IndexError, OverflowError):
                pass
            stack = []

    def _do(self, res, name, ctm, depth):
        pdf = self.pdf
        xobjs = pdf.resolve(res.get("XObject")) if isinstance(res, dict) else None
        if not isinstance(xobjs, dict):
            return
        xo = pdf.resolve(xobjs.get(name))
        if not isinstance(xo, Stream):
            return
        sub = pdf.resolve(xo.dict.get("Subtype"))
        if sub == "Image":
            area = abs(ctm[0] * ctm[3] - ctm[1] * ctm[2])
            page_area = max(self.out.width * self.out.height, 1.0)
            self.out.images.append((xo, area / page_area))
        elif sub == "Form" and depth < MAX_FORM_DEPTH:
            m = pdf.resolve(xo.dict.get("Matrix"))
            matrix = tuple(_num(pdf.resolve(v)) for v in m) if isinstance(m, list) and len(m) == 6 else IDENTITY
            fres = pdf.resolve(xo.dict.get("Resources"))
            try:
                body = decode_stream(xo)
            except PdfError:
                return
            self.run(body, fres if isinstance(fres, dict) else res, mul(matrix, ctm), depth + 1)

    def _inline_image(self, lex, ctm):
        data = lex.data
        # skip the dictionary-like key/value pairs up to ID
        for _ in range(200):
            try:
                t = lex.read()
            except PdfError:
                return
            if isinstance(t, Op) and str(t) == "ID":
                break
        else:
            return
        start = lex.pos + 1
        i = start
        while True:
            i = data.find(b"EI", i)
            if i < 0:
                lex.pos = len(data)
                return
            before_ok = i == start or data[i - 1:i] in (b" ", b"\n", b"\r", b"\t")
            after_ok = i + 2 >= len(data) or data[i + 2:i + 3] in (b" ", b"\n", b"\r", b"\t")
            if before_ok and after_ok:
                break
            i += 2
        lex.pos = i + 2


def read_page(pdf, page):
    data = PageData()
    x0, y0, x1, y1 = _box(pdf, page)
    rot = pdf.resolve(page.get("Rotate"))
    rot = int(rot) % 360 if isinstance(rot, (int, float)) else 0
    data.rotate = rot if rot in (90, 180, 270) else 0
    data.width, data.height = (y1 - y0, x1 - x0) if data.rotate in (90, 270) else (x1 - x0, y1 - y0)
    res = pdf.resolve(page.get("Resources"))
    res = res if isinstance(res, dict) else {}
    content = pdf.content_bytes(page)
    reader = _Reader(pdf, data)
    reader.run(content, res, (1.0, 0.0, 0.0, 1.0, -x0, -y0))
    for f in reader.fonts.values():
        if f is not None:
            data.mapped += f.mapped
            data.unmapped += f.unmapped
    limit = 20000.0
    data.chunks = [c for c in data.chunks if all(math.isfinite(v) and abs(v) < limit for v in (c.x0, c.x1, c.y, c.size))]
    for c in data.chunks:
        c.size = min(c.size, 500.0)
    if data.rotate in (90, 270) and data.chunks:
        # text on a sideways page runs up or down: we do not read it (OCR or a clear message instead)
        data.chunks = []
        data.unmapped += 1000
    # tidy characters
    for c in data.chunks:
        for bad, good in PRIVATE_USE_BULLETS.items():
            if bad in c.text:
                c.text = c.text.replace(bad, good)
        c.text = c.text.replace("�", "") if c.text.count("�") * 2 < len(c.text) else c.text
    return data


# ---------------------------------------------------------------- layout

class _Line:
    __slots__ = ("y", "size", "cells")

    def __init__(self, y, size, cells):
        self.y, self.size, self.cells = y, size, cells   # cells: list of [x0, x1, text, size]

    def text(self):
        return " ".join(c[2] for c in self.cells)


def _group_lines(chunks):
    chunks = [c for c in chunks if c.text.strip() and c.x1 >= c.x0 - 0.5]
    chunks.sort(key=lambda c: (-c.y, c.x0))
    rows = []
    for c in chunks:
        for row in reversed(rows[-4:]):
            tol = max(0.8, 0.42 * min(row[0].size, c.size))
            if abs(row[0].y - c.y) <= tol:
                row.append(c)
                break
        else:
            rows.append([c])
    lines = []
    for row in rows:
        row.sort(key=lambda c: c.x0)
        size = statistics.median(c.size for c in row)
        cells = []
        trailing = False
        for c in row:
            text = c.text.strip()
            if not text:
                continue
            lead = c.text[:1].isspace()
            if cells:
                prev = cells[-1]
                gap = c.x0 - prev[1]
                if gap <= 1.2 * size:
                    sep = " " if (gap > 0.16 * size or lead or trailing) else ""
                    prev[2] = prev[2] + sep + text
                    prev[1] = max(prev[1], c.x1)
                    prev[3] = max(prev[3], c.size)
                    trailing = c.text[-1:].isspace()
                    continue
            cells.append([c.x0, c.x1, text, c.size])
            trailing = c.text[-1:].isspace()
        if cells:
            lines.append(_Line(statistics.mean(c.y for c in row), size, cells))
    lines.sort(key=lambda ln: -ln.y)
    return lines


def _find_gutter(lines):
    n = len(lines)
    if n < 8:
        return None
    x_min = min(ln.cells[0][0] for ln in lines)
    x_max = max(ln.cells[-1][1] for ln in lines)
    width = x_max - x_min
    if width < 150 or width > 6000:
        return None
    med = statistics.median(ln.size for ln in lines)
    min_gap = max(10.0, 1.0 * med)
    tol = max(2, int(0.10 * n))
    step = 2.0
    good = []
    x = x_min + 0.12 * width
    end = x_max - 0.12 * width
    while x <= end:
        crossing = 0
        for ln in lines:
            for c in ln.cells:
                if c[0] < x < c[1]:
                    crossing += 1
                    break
        good.append((x, crossing <= tol))
        x += step
    candidates = []
    start = None
    prev = None
    for x, ok in good + [(end + step * 2, False)]:
        if ok and start is None:
            start = x
        if not ok and start is not None:
            lo, hi = start, prev + step
            if hi - lo >= min_gap:
                candidates.append((lo, hi))
            start = None
        prev = x
    best = None
    for lo0, hi0 in candidates:
        mid = (lo0 + hi0) / 2.0
        crossing = left_only = right_only = 0
        lo, hi = x_min, x_max
        for ln in lines:
            left = right = cross = False
            for c in ln.cells:
                if c[1] <= mid:
                    left = True
                    lo = max(lo, c[1]) if lo != x_min or True else lo
                elif c[0] >= mid:
                    right = True
                else:
                    cross = True
            if cross:
                crossing += 1
            else:
                left_only += 1 if left else 0
                right_only += 1 if right else 0
        # the tight gutter: from the right edge of the left cells to the left edge of the right cells
        left_edge = max((c[1] for ln in lines for c in ln.cells if c[1] <= mid), default=x_min)
        right_edge = min((c[0] for ln in lines for c in ln.cells if c[0] >= mid), default=x_max)
        if right_edge - left_edge < min_gap:
            continue
        if crossing > tol or left_only < 3 or right_only < 3 or left_only + right_only < 8:
            continue
        score = (min(left_only, right_only), right_edge - left_edge)
        if best is None or score > best[0]:
            best = (score, left_edge, right_edge)
    return (best[1], best[2]) if best else None


def _split_line(ln, lo, hi):
    left = [c for c in ln.cells if c[1] <= lo]
    right = [c for c in ln.cells if c[0] >= hi]
    def part(cells):
        return _Line(ln.y, max(c[3] for c in cells), cells) if cells else None
    return part(left), part(right)


def _crosses(ln, lo, hi):
    return any(c[1] > lo and c[0] < hi for c in ln.cells)


def order_lines(lines):
    """Reading order. Two-column pages are read one column after the other."""
    gutter = _find_gutter(lines)
    if gutter is None:
        return lines
    lo, hi = gutter
    out = []
    block = []

    def flush():
        if not block:
            return
        left, right = [], []
        for ln in block:
            a, b = _split_line(ln, lo, hi)
            if a:
                left.append(a)
            if b:
                right.append(b)
        left_size = max((ln.size for ln in left), default=0)
        right_size = max((ln.size for ln in right), default=0)
        right_first = right_size >= 1.25 * left_size and left_size > 0 and right_size >= 1.25 * statistics.median(
            ln.size for ln in block)
        out.extend(right + left if right_first else left + right)
        out.append(None)   # a break between the two columns
        block.clear()

    for ln in lines:
        if _crosses(ln, lo, hi):
            flush()
            out.append(ln)
        else:
            block.append(ln)
    flush()
    return out


def layout(chunks):
    """Page text: lines in reading order, a blank line between paragraphs."""
    lines = _group_lines(chunks)
    if not lines:
        return ""
    ordered = order_lines(lines[:4000])
    gaps = [a.y - b.y for a, b in zip(lines, lines[1:]) if a.y - b.y > 0.5]
    pitch = statistics.median(gaps) if gaps else 12.0
    out = []
    prev = None
    for ln in ordered:
        if ln is None:
            if out and out[-1] != "":
                out.append("")
            prev = None
            continue
        if prev is not None and prev.y - ln.y > 1.75 * pitch and out and out[-1] != "":
            out.append("")
        out.append(ln.text())
        prev = ln
    return "\n".join(out).strip("\n")


def text_quality(data):
    """Share of characters that could be turned into real text (1.0 = all)."""
    total = data.mapped + data.unmapped
    return 1.0 if total == 0 else data.mapped / total
