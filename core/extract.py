"""Get plain text out of an uploaded resume file. Only the PDF part uses an outside package.

Supported: .txt, .docx and .pdf, all with our own code (standard library only).
PDFs are read by core/pdfread.py. Scanned pages (a picture and no text) are read with
Tesseract (core/ocr.py) when it is installed; the result then carries `.ocr = True`.

Safety rules:
- the file type is decided by the file's own bytes, not just the name
- size limits on the upload and on the unzipped XML (zip bombs)
- XML that declares entities or a DOCTYPE is refused
"""

import io
import re
import xml.etree.ElementTree as ET
import zipfile

from .ocr import OcrBusy  # noqa: F401  (re-exported so callers can map it to HTTP 503)

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_XML_BYTES = 5 * 1024 * 1024
MAX_ZIP_ENTRIES = 200
MAX_PDF_PAGES = 10

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


class ExtractError(ValueError):
    """The file cannot be used. The message is safe to show to the user."""


def extract_text(filename, data):
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ExtractError("the file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ExtractError("the file is too large (limit 2 MB)")
    name = (filename or "").lower()
    if data[:5] == b"%PDF-":
        return _pdf_text(bytes(data))
    if name.endswith(".pdf"):
        raise ExtractError("this is not a valid PDF file")
    if data[:2] == b"PK":
        return _docx_text(bytes(data))
    if name.endswith(".docx"):
        raise ExtractError("this is not a valid DOCX file")
    if name.endswith(".txt") or not name:
        return _plain_text(bytes(data))
    raise ExtractError("unsupported file type; upload DOCX or TXT")


class Result(str):
    """The text, plus a flag: `ocr` is True when some of it was read from a scanned picture."""
    ocr = False


_MIN_TEXT = 20          # fewer characters than this on a page = the page has no real text
_SCAN_IMAGE_SHARE = 0.4  # a picture over at least this share of the page = a scan
_MAX_OCR_PAGES = 3
_MIN_QUALITY = 0.6      # below this share of readable characters the fonts are garbled


def _pdf_text(data):
    """Text of a PDF with our own reader (core/pdfread.py). Scanned pages go to OCR when it is installed."""
    from . import ocr, pdfimage, pdfread, pdftext
    try:
        pdf = pdfread.Pdf(data)
        pages = pdf.pages()
        if not pages:
            raise ExtractError("could not read this PDF")
        if len(pages) > MAX_PDF_PAGES:
            raise ExtractError("the PDF has too many pages (limit %d)" % MAX_PDF_PAGES)
        texts, scans = [], []
        for number, page in enumerate(pages):
            info = pdftext.read_page(pdf, page)
            text = pdftext.layout(info.chunks)
            if len(text.strip()) >= _MIN_TEXT and pdftext.text_quality(info) < _MIN_QUALITY:
                text = ""
            texts.append(text)
            if len(text.strip()) < _MIN_TEXT:
                big = [im for im in info.images if im[1] >= _SCAN_IMAGE_SHARE]
                if big:
                    scans.append((number, max(big, key=lambda im: im[1])[0], info.width))
        used_ocr = False
        if scans:
            have_text = any(len(t.strip()) >= _MIN_TEXT for t in texts)
            if not ocr.available():
                if not have_text:
                    raise ExtractError("this looks like a scanned PDF and reading scans is not set up on this server. Upload DOCX or paste the text")
            else:
                for number, stream, width_pt in scans[:_MAX_OCR_PAGES]:
                    try:
                        _, image = pdfimage.image_file(stream)
                        px = pdf.resolve(stream.dict.get("Width"))
                        dpi = px / (width_pt / 72.0) if isinstance(px, int) and width_pt > 0 else None
                        found = ocr.read_image(image, dpi)
                    except ocr.OcrBusy:
                        raise
                    except (ocr.OcrError, pdfread.PdfError) as exc:
                        if not have_text and not used_ocr:
                            raise ExtractError(str(exc))
                        continue
                    texts[number] = found
                    used_ocr = True
    except (ExtractError, ocr.OcrBusy):
        raise
    except pdfread.PdfEncrypted:
        raise ExtractError("the PDF is password protected; remove the password and upload again")
    except (pdfread.PdfError, ValueError, KeyError, TypeError, IndexError, OSError, RecursionError, MemoryError, OverflowError, ZeroDivisionError):
        raise ExtractError("could not read this PDF")
    text = _unwrap(_drop_page_noise(_join_spaced_letters(_clean_chars("\n\n".join(texts)))))
    text = _tidy(text)
    if len(text) < _MIN_TEXT:
        raise ExtractError("no text found; this may be a scanned PDF. Upload DOCX or paste the text")
    result = Result(text)
    result.ocr = used_ocr
    return result


def _plain_text(data):
    if b"\x00" in data:
        raise ExtractError("this does not look like a text file")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ExtractError("could not read the text encoding")
    return _tidy(text)


def _docx_text(data):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ExtractError("this is not a valid DOCX file")
    if len(archive.infolist()) > MAX_ZIP_ENTRIES:
        raise ExtractError("the file has too many parts")
    if "word/document.xml" not in archive.namelist():
        raise ExtractError("this is not a Word document")
    body = _docx_part_lines(archive, "word/document.xml", strict=True)
    # Contact details are often kept in the page header; footers (page numbers) are skipped.
    headers = []
    for name in sorted(n for n in archive.namelist() if re.fullmatch(r"word/header\d*\.xml", n))[:3]:
        for line in _docx_part_lines(archive, name, strict=False):
            if line and line not in headers and line not in body:
                headers.append(line)
    return _tidy("\n".join(headers + body))


def _docx_part_lines(archive, name, strict):
    """Text lines of one Word part. strict=False swallows problems (used for optional parts)."""
    try:
        info = archive.getinfo(name)
        if info.file_size > MAX_XML_BYTES:
            raise ExtractError("the document is too large")
        with archive.open(info) as handle:
            xml_bytes = handle.read(MAX_XML_BYTES + 1)
        if len(xml_bytes) > MAX_XML_BYTES:
            raise ExtractError("the document is too large")
        head = xml_bytes.upper()
        if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
            raise ExtractError("the document contains unsupported content")
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            raise ExtractError("could not read the document")
    except ExtractError:
        if strict:
            raise
        return []
    # Word stores shapes twice (a modern copy and a fallback copy); keep only one.
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag == MC + "Fallback":
                parent.remove(child)
    lines = []
    for paragraph in root.iter(W + "p"):
        text = _paragraph_text(paragraph)
        if not text.strip():
            lines.append("")
            continue
        is_list = paragraph.find("%spPr/%snumPr" % (W, W)) is not None
        lines.append(("- " + text.strip()) if is_list else text.strip())
    return lines


def _paragraph_text(paragraph):
    """Text of one paragraph. Text boxes inside it are separate paragraphs and are not mixed in."""
    parts = []

    def walk(node):
        for child in node:
            if child.tag == W + "txbxContent":
                continue
            if child.tag == W + "t":
                parts.append(child.text or "")
            elif child.tag == W + "tab":
                parts.append(" ")
            elif child.tag in (W + "br", W + "cr"):
                parts.append("\n")
            else:
                walk(child)

    walk(paragraph)
    return "".join(parts)


def _tidy(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_SPACED_TOKEN = re.compile(r"^[A-Za-z&]{1,2}$")
_PAGE_NOISE = re.compile(r"^\s*(?:page\s+\d+(?:\s+(?:of|/)\s+\d+)?|\d+\s*/\s*\d+)\s*$", re.I)


def _join_spaced_letters(text):
    """Canva-style headings come out as "E D U C AT I O N" (letters with gaps; words with a wider gap).
    Join the letters back into words. Only lines made of at least 4 tiny tokens are touched."""
    out = []
    for line in text.split("\n"):
        tokens = line.split()
        if len(tokens) >= 4 and all(_SPACED_TOKEN.match(t) for t in tokens) and sum(len(t) == 1 for t in tokens) >= 0.7 * len(tokens):
            words = re.split(r" {2,}", line.strip())
            line = " ".join(w.replace(" ", "") for w in words)
        out.append(line)
    return "\n".join(out)


def _drop_page_noise(text):
    """Remove footer lines such as "Page 1 of 2" that PDFs repeat on every page."""
    return "\n".join(ln for ln in text.split("\n") if not _PAGE_NOISE.match(ln))


_LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
              "\u00a0": " ", "\u00ad": "", "\u200b": "", "\u2022": "\u2022"}
_BULLET_START = re.compile(r"^\s*(?:[-*\u2022\u25cf\u25aa\u2023\u2013\u2014\u25ba\u25b6\u25e6\u25cb\u25a0\u25a1\u2713\u2714\u27a2\u27a4\u2794\u2192]|\d{1,2}[.)])\s")
_LABEL_START = re.compile(r"^[A-Z][\w /&-]{1,24}:\s")  # "Tools: Jira" starts a new line, not a wrap
_HEADING_LIKE = re.compile(r"^[A-Z][A-Z &/]{2,38}:?$")


def _clean_chars(text):
    """Fix characters that PDFs commonly produce: ligatures, odd spaces, control characters."""
    for bad, good in _LIGATURES.items():
        text = text.replace(bad, good)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


def _unwrap(text):
    """Join lines that a PDF broke only because the page was full.

    A line is joined to the next one only when it is nearly as wide as the widest line
    in the file, does not end a sentence, and the next line is not a bullet, a heading
    or a blank line. Short lines (names, contact lines, titles) are never joined.
    """
    lines = text.split("\n")
    widest = max((len(ln.strip()) for ln in lines), default=0)
    if widest < 40:
        return text
    out = []
    for line in lines:
        previous = out[-1] if out else ""
        stripped = line.strip()
        if (
            previous.strip()
            and stripped
            and (
                previous.rstrip().endswith(("-", "\u2013", ","))
                or (
                    len(previous.strip()) >= 0.9 * widest
                    and not previous.rstrip().endswith((".", ":", ";", "!", "?"))
                )
            )
            and not _BULLET_START.match(line)
            and not _LABEL_START.match(stripped)
            and not _HEADING_LIKE.match(stripped)
        ):
            out[-1] = previous.rstrip() + " " + stripped
        else:
            out.append(line)
    return "\n".join(out)
