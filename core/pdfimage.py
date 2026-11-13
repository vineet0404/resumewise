"""Our own PDF reader, part 4: page images (for scanned CVs).

A scanned PDF is a picture of a page. This file pulls that picture out of the PDF and gives it back as a
normal image file (JPEG as it is, other pixel data wrapped into a PNG that we write ourselves), ready
for OCR. Supported: JPEG (what phone scanner apps make) and raw/Flate/LZW pixel data in gray, RGB,
palette and CMYK. Not supported: JBIG2 and CCITT fax (office scanner hardware); a clear error says so.
"""

import struct
import zlib

from .pdfread import PdfError, Stream, decode_stream

MAX_PIXELS = 30_000_000


def _png(width, height, depth, color_type, rows, palette=None):
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, color_type, 0, 0, 0))
    if palette:
        out += chunk(b"PLTE", palette)
    out += chunk(b"IDAT", zlib.compress(rows, 6))
    return out + chunk(b"IEND", b"")


def _colorspace(pdf, cs):
    """-> (components, palette or None). Palette is RGB bytes for Indexed spaces."""
    cs = pdf.resolve(cs)
    if isinstance(cs, str):
        if cs in ("DeviceGray", "G", "CalGray"):
            return 1, None
        if cs in ("DeviceRGB", "RGB", "CalRGB"):
            return 3, None
        if cs in ("DeviceCMYK", "CMYK"):
            return 4, None
        raise PdfError("unsupported image colour space")
    if isinstance(cs, list) and cs:
        kind = str(pdf.resolve(cs[0]))
        if kind == "ICCBased" and len(cs) > 1:
            stm = pdf.resolve(cs[1])
            n = pdf.resolve(stm.dict.get("N")) if isinstance(stm, Stream) else None
            if n in (1, 3, 4):
                return n, None
        if kind in ("CalGray",):
            return 1, None
        if kind in ("CalRGB", "Lab"):
            return 3, None
        if kind in ("Indexed", "I") and len(cs) >= 4:
            base, _ = _colorspace(pdf, cs[1])
            hival = int(pdf.resolve(cs[2]))
            lookup = pdf.resolve(cs[3])
            if isinstance(lookup, Stream):
                lookup = decode_stream(lookup)
            if not isinstance(lookup, (bytes, bytearray)):
                raise PdfError("unsupported palette")
            pal = bytearray()
            for i in range(min(hival, 255) + 1):
                entry = lookup[i * base:(i + 1) * base]
                if len(entry) < base:
                    entry = entry + bytes(base - len(entry))
                if base == 1:
                    pal += bytes([entry[0]] * 3)
                elif base == 3:
                    pal += entry
                else:
                    pal += _cmyk_to_rgb(entry)
            return -1, bytes(pal)
    raise PdfError("unsupported image colour space")


def _cmyk_to_rgb(px):
    c, m, y, k = px[0], px[1], px[2], px[3]
    return bytes(((255 - c) * (255 - k) // 255, (255 - m) * (255 - k) // 255, (255 - y) * (255 - k) // 255))


def image_file(stream):
    """(extension, bytes) of a PDF image XObject, or raise PdfError."""
    pdf = stream.pdf
    d = stream.dict
    width = pdf.resolve(d.get("Width", d.get("W")))
    height = pdf.resolve(d.get("Height", d.get("H")))
    if not (isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0):
        raise PdfError("bad image size")
    if width * height > MAX_PIXELS:
        raise PdfError("the scanned image is too large")
    data, remaining = decode_stream(stream, stop_at_image=True)
    if remaining:
        name = remaining[0][0]
        if name == "DCTDecode":
            if data[:2] != b"\xff\xd8":
                raise PdfError("damaged image")
            return "jpg", data
        if name == "JPXDecode":
            return "jp2", data
        if name in ("JBIG2Decode", "CCITTFaxDecode"):
            raise PdfError("this scan uses a fax-style image format we cannot read yet")
        raise PdfError("unsupported image format")
    bpc = pdf.resolve(d.get("BitsPerComponent", d.get("BPC")))
    is_mask = pdf.resolve(d.get("ImageMask", d.get("IM"))) is True
    if is_mask:
        bpc = 1
        n, palette = 1, None
    else:
        n, palette = _colorspace(pdf, d.get("ColorSpace", d.get("CS")))
    if not isinstance(bpc, int) or bpc not in (1, 2, 4, 8, 16):
        raise PdfError("unsupported image depth")
    comps = 1 if n == -1 else n
    stride = (width * comps * bpc + 7) // 8
    need = stride * height
    if len(data) < need:
        data = data + bytes(need - len(data))
    data = data[:need]
    decode = pdf.resolve(d.get("Decode", d.get("D")))
    invert = isinstance(decode, list) and len(decode) >= 2 and decode[0] == 1 and decode[1] == 0
    if invert and n == 1 and bpc <= 8:
        data = data.translate(bytes(i ^ 0xFF for i in range(256)))
    rows = b"".join(b"\x00" + data[y * stride:(y + 1) * stride] for y in range(height))
    if n == 1:
        return "png", _png(width, height, bpc, 0, rows)
    if n == 3:
        if bpc not in (8, 16):
            raise PdfError("unsupported image depth")
        return "png", _png(width, height, bpc, 2, rows)
    if n == -1:
        return "png", _png(width, height, bpc, 3, rows, palette)
    if n == 4:
        if bpc != 8 or width * height > 6_000_000:
            raise PdfError("unsupported image")
        out = bytearray()
        for y in range(height):
            out.append(0)
            row = data[y * stride:(y + 1) * stride]
            for x in range(0, len(row) - 3, 4):
                out += _cmyk_to_rgb(row[x:x + 4])
        return "png", _png(width, height, 8, 2, bytes(out))
    raise PdfError("unsupported image")
