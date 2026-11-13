"""Tests for our own PDF reader (core/pdfread.py, pdffonts.py, pdftext.py) and scanned-PDF OCR."""

import os
import sys
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import extract, ocr, pdfread  # noqa: E402
from pdfmaker import Builder, ascii85, lzw_encode  # noqa: E402

LINES = ["Aarti Sharma", "aarti@example.com | +91 98200 11122", "", "PROJECTS", "Tested twelve web modules for defects"]
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "scan_cv.jpg")


def one_page(mode="table", lines=LINES):
    b = Builder()
    page = b.text_page(lines)
    return b.finish_objstm([page]) if mode == "objstm" else b.finish([page], mode=mode)


class ReaderVariants(unittest.TestCase):
    def check(self, data):
        text = extract.extract_text("cv.pdf", data)
        self.assertIn("Aarti Sharma", text)
        self.assertIn("aarti@example.com", text)
        self.assertIn("PROJECTS", text)
        self.assertIn("Tested twelve web modules", text)

    def test_classic_table(self):
        self.check(one_page("table"))

    def test_cross_reference_stream(self):
        self.check(one_page("xrefstream"))

    def test_object_streams(self):
        self.check(one_page("objstm"))

    def test_no_cross_reference_table_is_rebuilt(self):
        self.check(one_page("none"))

    def test_wrong_startxref_is_rebuilt(self):
        data = one_page("table")
        i = data.rindex(b"startxref")
        self.check(data[:i] + b"startxref\n99999\n%%EOF\n")

    def test_truncated_file_never_crashes(self):
        data = one_page("table")
        for cut in range(10, len(data), max(1, len(data) // 40)):
            try:
                extract.extract_text("cv.pdf", data[:cut])
            except extract.ExtractError:
                pass

    def test_garbage_bytes_never_crash(self):
        import random
        rnd = random.Random(7)
        base = bytearray(one_page("table"))
        for _ in range(150):
            data = bytearray(base)
            for _ in range(rnd.randint(1, 12)):
                data[rnd.randrange(len(data))] = rnd.randrange(256)
            try:
                extract.extract_text("cv.pdf", bytes(data))
            except extract.ExtractError:
                pass

    def test_page_limit(self):
        b = Builder()
        pages = [b.text_page(["Page %d has some readable text here" % i]) for i in range(extract.MAX_PDF_PAGES + 1)]
        with self.assertRaises(extract.ExtractError) as ctx:
            extract.extract_text("cv.pdf", b.finish(pages))
        self.assertIn("too many pages", str(ctx.exception))


class Filters(unittest.TestCase):
    def build(self, filter_name, encode):
        b = Builder()
        font = b.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        raw = b"BT /F1 12 Tf 72 720 Td 14 TL (Aarti Sharma) Tj T* (Tested twelve web modules) Tj ET"
        data = encode(raw)
        content = b.add(("<< /Filter %s /Length %d >>\nstream\n" % (filter_name, len(data))).encode("latin-1") + data + b"\nendstream")
        pages_num = b.next + 1
        page = b.add("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] /Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> >>" % (pages_num, content, font))
        return b.finish([page])

    def test_lzw(self):
        self.assertIn("Tested twelve", extract.extract_text("a.pdf", self.build("/LZWDecode", lzw_encode)))

    def test_ascii85(self):
        self.assertIn("Tested twelve", extract.extract_text("a.pdf", self.build("/ASCII85Decode", ascii85)))

    def test_asciihex(self):
        enc = lambda raw: raw.hex().encode() + b">"  # noqa: E731
        self.assertIn("Tested twelve", extract.extract_text("a.pdf", self.build("/ASCIIHexDecode", enc)))

    def test_flate_then_ascii85(self):
        enc = lambda raw: ascii85(zlib.compress(raw))  # noqa: E731
        self.assertIn("Tested twelve", extract.extract_text("a.pdf", self.build("[/ASCII85Decode /FlateDecode]", enc)))

    def test_decompression_bomb_is_refused(self):
        bomb = zlib.compress(b"\0" * (200 * 1024 * 1024), 9)
        self.assertLess(len(bomb), 400000)
        b = Builder()
        content = b.add(("<< /Filter /FlateDecode /Length %d >>\nstream\n" % len(bomb)).encode() + bomb + b"\nendstream")
        pages_num = b.next + 1
        page = b.add("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] /Contents %d 0 R >>" % (pages_num, content))
        with self.assertRaises(extract.ExtractError):
            extract.extract_text("a.pdf", b.finish([page]))


class Encrypted(unittest.TestCase):
    def test_encrypted_pdf_is_refused(self):
        data = one_page("table")
        data = data.replace(b"/Root ", b"/Encrypt << /Filter /Standard /V 1 /R 2 /O (x) /U (y) /P -4 >> /Root ", 1)
        with self.assertRaises(extract.ExtractError) as ctx:
            extract.extract_text("cv.pdf", data)
        self.assertIn("password", str(ctx.exception))


class Layout(unittest.TestCase):
    def test_two_columns_are_read_one_after_the_other(self):
        b = Builder()
        font = b.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        ops = ["BT /F1 11 Tf"]
        left = ["Contact", "aarti@example.com", "Thane Maharashtra", "Skills", "Python and Django work",
                "Manual testing", "Selenium basics", "Languages", "English and Hindi", "Marathi"]
        right = ["Experience", "Software tester at Acme", "Wrote test cases for billing", "Found many defects early", "Education",
                 "MCA Mumbai University", "BSc IT Thane", "Projects", "ResumeWise assistant", "Built with Django"]
        for i, (a, c) in enumerate(zip(left, right)):
            y = 760 - i * 18
            ops.append("1 0 0 1 40 %d Tm (%s) Tj 1 0 0 1 330 %d Tm (%s) Tj" % (y, a, y, c))
        ops.append("ET")
        content = b.stream("", "\n".join(ops).encode())
        pages_num = b.next + 1
        page = b.add("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595 842] /Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> >>" % (pages_num, content, font))
        text = extract.extract_text("cv.pdf", b.finish([page]))
        self.assertLess(text.index("Python and Django"), text.index("Experience"))

    def test_winansi_characters(self):
        data = one_page("table", ["Caf\xe9 R\xe9sum\xe9 \x95 bullet point text here"])
        text = extract.extract_text("cv.pdf", data)
        self.assertIn("R\xe9sum\xe9", text)


def scan_pdf(extra_text_page=False):
    jpg = open(FIXTURE, "rb").read()
    b = Builder()
    pages = []
    if extra_text_page:
        pages.append(b.text_page(["Typed first page with plenty of readable words in it"]))
    pages.append(b.image_page("/Width 1241 /Height 1754 /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /DCTDecode", jpg))
    return b.finish(pages)


@unittest.skipUnless(ocr.available(), "Tesseract is not installed")
class ScannedPdf(unittest.TestCase):
    def test_scan_is_read_and_flagged(self):
        text = extract.extract_text("scan.pdf", scan_pdf())
        self.assertTrue(text.ocr)
        self.assertIn("AMIT", text.upper())
        self.assertIn("amit.sharma2001@gmail.com", text.replace(" ", ""))

    def test_text_pdf_is_not_flagged(self):
        self.assertFalse(extract.extract_text("cv.pdf", one_page("table")).ocr)

    def test_mixed_pdf_keeps_typed_page_and_reads_scan(self):
        text = extract.extract_text("mix.pdf", scan_pdf(extra_text_page=True))
        self.assertTrue(text.ocr)
        self.assertIn("Typed first page", text)
        self.assertIn("AMIT", text.upper())

    def test_busy_ocr_is_reported(self):
        saved = ocr._SLOTS
        import threading
        ocr._SLOTS = threading.BoundedSemaphore(1)
        ocr._SLOTS.acquire()
        try:
            with self.assertRaises(ocr.OcrBusy):
                extract.extract_text("scan.pdf", scan_pdf())
        finally:
            ocr._SLOTS = saved


class ScannedWithoutOcr(unittest.TestCase):
    def test_clear_message_when_ocr_is_off(self):
        old = os.environ.get("OCR_ENABLED")
        os.environ["OCR_ENABLED"] = "0"
        try:
            with self.assertRaises(extract.ExtractError) as ctx:
                extract.extract_text("scan.pdf", scan_pdf())
        finally:
            if old is None:
                del os.environ["OCR_ENABLED"]
            else:
                os.environ["OCR_ENABLED"] = old
        self.assertIn("scanned", str(ctx.exception))

    def test_fax_style_scan_gives_clear_message(self):
        b = Builder()
        page = b.image_page("/Width 100 /Height 100 /ColorSpace /DeviceGray /BitsPerComponent 1 /Filter /JBIG2Decode", b"\0" * 20)
        old = os.environ.get("OCR_ENABLED")
        try:
            with self.assertRaises(extract.ExtractError):
                extract.extract_text("scan.pdf", b.finish([page]))
        finally:
            if old is not None:
                os.environ["OCR_ENABLED"] = old


if __name__ == "__main__":
    unittest.main()
