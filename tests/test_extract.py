import io
import unittest
import zipfile

from core import extract

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_docx(paragraphs, extra_xml_head=""):
    body = ""
    for text, is_list in paragraphs:
        ppr = "<w:pPr><w:numPr><w:ilvl w:val=\"0\"/><w:numId w:val=\"1\"/></w:numPr></w:pPr>" if is_list else ""
        body += "<w:p>%s<w:r><w:t>%s</w:t></w:r></w:p>" % (ppr, text)
    xml = "%s<w:document xmlns:w=\"%s\"><w:body>%s</w:body></w:document>" % (extra_xml_head, W, body)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


class ExtractTests(unittest.TestCase):
    def test_docx_keeps_headings_and_bullets(self):
        data = make_docx([("Aarti Sharma", False), ("PROJECTS", False), ("Tested 12 modules", True)])
        text = extract.extract_text("cv.docx", data)
        self.assertEqual(text, "Aarti Sharma\nPROJECTS\n- Tested 12 modules")

    def test_txt_utf8_and_cp1252(self):
        self.assertEqual(extract.extract_text("a.txt", "caf\u00e9\r\nok".encode("utf-8")), "caf\u00e9\nok")
        self.assertEqual(extract.extract_text("a.txt", "caf\u00e9".encode("cp1252")), "caf\u00e9")

    def test_empty_pdf_and_unknown_types_are_refused(self):
        for name, data in [("a.txt", b""), ("a.pdf", b"%PDF-1.4 x"), ("a.pdf", b"not a pdf"), ("a.exe", b"MZ\x90abc"), ("a.docx", b"not a zip")]:
            with self.assertRaises(extract.ExtractError):
                extract.extract_text(name, data)

    def test_binary_in_txt_is_refused(self):
        with self.assertRaises(extract.ExtractError):
            extract.extract_text("a.txt", b"abc\x00\x01")

    def test_entity_tricks_are_refused(self):
        bad = make_docx([("x", False)], extra_xml_head="<!DOCTYPE d [<!ENTITY a \"b\">]>")
        with self.assertRaises(extract.ExtractError):
            extract.extract_text("cv.docx", bad)

    def test_oversized_upload_and_xml_are_refused(self):
        with self.assertRaises(extract.ExtractError):
            extract.extract_text("a.txt", b"a" * (extract.MAX_UPLOAD_BYTES + 1))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", b"<a>" + b"x" * (extract.MAX_XML_BYTES + 10) + b"</a>")
        self.assertLess(len(buf.getvalue()), extract.MAX_UPLOAD_BYTES)
        with self.assertRaises(extract.ExtractError):
            extract.extract_text("cv.docx", buf.getvalue())

    def test_zip_without_word_document_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("other.txt", "hi")
        with self.assertRaises(extract.ExtractError):
            extract.extract_text("cv.docx", buf.getvalue())


def make_pdf(lines):
    """A tiny valid one-page PDF with the given text lines."""
    content = "BT /F1 12 Tf 72 720 Td 14 TL " + " ".join("(%s) Tj T*" % ln for ln in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        "<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += ("%d 0 obj\n%s\nendobj\n" % (i, body)).encode("latin-1")
    xref = len(out)
    out += ("xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)).encode()
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)).encode()
    return out


class PdfTests(unittest.TestCase):
    def test_pdf_text_is_extracted(self):
        data = make_pdf(["Aarti Sharma", "PROJECTS", "Tested twelve web modules for defects"])
        text = extract.extract_text("cv.pdf", data)
        self.assertIn("Aarti Sharma", text)
        self.assertIn("PROJECTS", text)

    def test_pdf_detected_by_bytes_even_with_wrong_name(self):
        data = make_pdf(["Tested twelve web modules for defects"])
        self.assertIn("Tested twelve", extract.extract_text("resume.txt", data))

    def test_pdf_without_text_is_called_scanned(self):
        with self.assertRaises(extract.ExtractError) as ctx:
            extract.extract_text("cv.pdf", make_pdf([""]))
        self.assertIn("scanned", str(ctx.exception))

    def test_damaged_pdf_gives_a_clean_error(self):
        data = make_pdf(["Tested twelve web modules for defects"])
        with self.assertRaises(extract.ExtractError):
            extract.extract_text("cv.pdf", data[: len(data) // 3])
