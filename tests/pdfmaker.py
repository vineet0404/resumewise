"""A tiny PDF writer for tests (so the tests do not need any PDF library or program)."""

import zlib


def lzw_encode(data):
    """Minimal LZW encoder (clear code each 200 codes keeps the code size at 9..10 bits)."""
    out = bytearray()
    bits = 0
    nbits = 0

    def emit(code, width):
        nonlocal bits, nbits
        bits = (bits << width) | code
        nbits += width
        while nbits >= 8:
            out.append((bits >> (nbits - 8)) & 0xFF)
            nbits -= 8
        bits &= (1 << nbits) - 1

    table = {bytes([i]): i for i in range(256)}
    nxt = 258
    width = 9
    emit(256, width)
    w = b""
    for b in data:
        wc = w + bytes([b])
        if wc in table:
            w = wc
        else:
            emit(table[w], width)
            table[wc] = nxt
            nxt += 1
            if nxt + 1 > 511 and width == 9:
                width = 10
            if nxt + 1 > 1023 and width == 10:
                emit(256, width)
                table = {bytes([i]): i for i in range(256)}
                nxt = 258
                width = 9
            w = bytes([b])
    if w:
        emit(table[w], width)
    emit(257, width)
    if nbits:
        out.append((bits << (8 - nbits)) & 0xFF)
    return bytes(out)


def ascii85(data):
    out = bytearray()
    for i in range(0, len(data), 4):
        chunk = data[i:i + 4]
        n = len(chunk)
        v = int.from_bytes(chunk + bytes(4 - n), "big")
        if v == 0 and n == 4:
            out += b"z"
            continue
        digits = []
        for _ in range(5):
            digits.append(v % 85 + 33)
            v //= 85
        out += bytes(reversed(digits))[:n + 1]
    return bytes(out) + b"~>"


def esc(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class Builder:
    """Collects objects, writes a PDF with a classic table, a cross-reference stream, or no table at all."""

    def __init__(self):
        self.objs = {}
        self.next = 1

    def add(self, body, num=None):
        if num is None:
            num = self.next
        self.next = max(self.next, num + 1)
        self.objs[num] = body if isinstance(body, bytes) else body.encode("latin-1")
        return num

    def stream(self, dict_text, data, compress=True, num=None):
        if compress:
            data = zlib.compress(data)
            dict_text += " /Filter /FlateDecode"
        body = ("<< %s /Length %d >>\nstream\n" % (dict_text, len(data))).encode("latin-1") + data + b"\nendstream"
        return self.add(body, num)

    def text_page(self, lines, font_dict="/Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding",
                  size=11, x=50, top=780, leading=16, media="0 0 595 842", extra_page=""):
        font = self.add("<< %s >>" % font_dict)
        ops = ["BT /F1 %d Tf %d TL %d %d Td" % (size, leading, x, top)]
        for ln in lines:
            ops.append("(%s) Tj T*" % esc(ln))
        ops.append("ET")
        content = self.stream("", "\n".join(ops).encode("latin-1"))
        pages_num = self.next + 1
        page = self.add("<< /Type /Page /Parent %d 0 R /MediaBox [%s] /Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> %s >>"
                        % (pages_num, media, content, font, extra_page))
        return page

    def finish(self, page_nums, mode="table", version="1.4"):
        pages = self.add("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % p for p in page_nums), len(page_nums)))
        # keep numbering stable: the Pages object is the one the pages point to
        for p in page_nums:
            self.objs[p] = self.objs[p].replace(b"/Parent %d 0 R" % (pages + 0), b"/Parent %d 0 R" % pages)
        root = self.add("<< /Type /Catalog /Pages %d 0 R >>" % pages)
        out = bytearray(("%%PDF-%s\n" % version).encode() + b"%\xe2\xe3\xcf\xd3\n")
        offsets = {}
        for num in sorted(self.objs):
            offsets[num] = len(out)
            out += b"%d 0 obj\n" % num + self.objs[num] + b"\nendobj\n"
        size = max(self.objs) + 1
        if mode == "table":
            start = len(out)
            out += b"xref\n0 %d\n" % size
            out += b"0000000000 65535 f \n"
            for num in range(1, size):
                out += (b"%010d 00000 n \n" % offsets[num]) if num in offsets else b"0000000000 65535 f \n"
            out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, root, start)
        elif mode == "xrefstream":
            xnum = size
            start = len(out)
            rows = bytearray()
            rows += b"\x00" + (0).to_bytes(4, "big") + b"\xff\xff"
            for num in range(1, size):
                rows += b"\x01" + offsets.get(num, 0).to_bytes(4, "big") + b"\x00\x00"
            rows += b"\x01" + start.to_bytes(4, "big") + b"\x00\x00"
            data = zlib.compress(bytes(rows))
            out += b"%d 0 obj\n<< /Type /XRef /Size %d /W [1 4 2] /Root %d 0 R /Filter /FlateDecode /Length %d >>\nstream\n" % (xnum, size + 1, root, len(data))
            out += data + b"\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % start
        elif mode == "none":      # no cross-reference table at all: the reader must scan the file
            out += b"trailer\n<< /Root %d 0 R >>\n" % root
        return bytes(out)

    def finish_objstm(self, page_nums):
        """Pages/Catalog/Page dictionaries packed in an object stream, with a cross-reference stream (PDF 1.5)."""
        pages = self.add("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % p for p in page_nums), len(page_nums)))
        root = self.add("<< /Type /Catalog /Pages %d 0 R >>" % pages)
        packed = [n for n in sorted(self.objs) if not self.objs[n].lstrip().startswith(b"<<") or b"stream" in self.objs[n]]
        packable = [n for n in sorted(self.objs) if b"stream" not in self.objs[n] and n != 0]
        header, body = [], bytearray()
        for n in packable:
            header.append("%d %d" % (n, len(body)))
            body += self.objs[n] + b" "
        head = (" ".join(header) + "\n").encode()
        stm_data = zlib.compress(head + bytes(body))
        stm_num = max(self.objs) + 1
        out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
        offsets = {}
        for n in sorted(self.objs):
            if n in packable:
                continue
            offsets[n] = len(out)
            out += b"%d 0 obj\n" % n + self.objs[n] + b"\nendobj\n"
        offsets[stm_num] = len(out)
        out += b"%d 0 obj\n<< /Type /ObjStm /N %d /First %d /Filter /FlateDecode /Length %d >>\nstream\n" % (stm_num, len(packable), len(head), len(stm_data))
        out += stm_data + b"\nendstream\nendobj\n"
        xnum = stm_num + 1
        start = len(out)
        rows = bytearray()
        for n in range(0, xnum + 1):
            if n == 0:
                rows += b"\x00" + (0).to_bytes(4, "big") + b"\xff\xff"
            elif n in packable:
                rows += b"\x02" + stm_num.to_bytes(4, "big") + packable.index(n).to_bytes(2, "big")
            elif n == xnum:
                rows += b"\x01" + start.to_bytes(4, "big") + b"\x00\x00"
            else:
                rows += b"\x01" + offsets.get(n, 0).to_bytes(4, "big") + b"\x00\x00"
        data = zlib.compress(bytes(rows))
        out += b"%d 0 obj\n<< /Type /XRef /Size %d /W [1 4 2] /Root %d 0 R /Filter /FlateDecode /Length %d >>\nstream\n" % (xnum, xnum + 1, root, len(data))
        out += data + b"\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % start
        return bytes(out)

    def image_page(self, image_dict, data, filters="", width_pt=595, height_pt=842, extra_page=""):
        """A page that is one picture over the whole page (what a scanner makes)."""
        img = self.add(("<< /Type /XObject /Subtype /Image %s %s /Length %d >>\nstream\n" % (image_dict, filters, len(data))).encode("latin-1") + data + b"\nendstream")
        content = self.stream("", ("q %d 0 0 %d 0 0 cm /Im0 Do Q" % (width_pt, height_pt)).encode())
        pages_num = self.next + 1
        return self.add("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R /Resources << /XObject << /Im0 %d 0 R >> >> %s >>"
                        % (pages_num, width_pt, height_pt, content, img, extra_page))
