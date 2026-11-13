import io
import struct
import unittest
import zlib

from core import image_check as ic


def png_chunk(ctype, body):
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF)


def make_png(width=200, height=200, extra=()):
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + b"\x80\x90\xa0" * width
    idat = zlib.compress(row * height)
    chunks = png_chunk(b"IHDR", ihdr)
    for ctype, body in extra:
        chunks += png_chunk(ctype, body)
    chunks += png_chunk(b"IDAT", idat) + png_chunk(b"IEND", b"")
    return ic.PNG_SIGNATURE + chunks


def jpeg_segment(marker, body):
    return bytes([0xFF, marker]) + struct.pack(">H", len(body) + 2) + body


def make_jpeg(width=200, height=200, with_exif=True, trailing=b""):
    out = b"\xff\xd8"
    if with_exif:
        out += jpeg_segment(0xE1, b"Exif\x00\x00GPS-LATITUDE-19.07N")
        out += jpeg_segment(0xFE, b"a private comment")
    out += jpeg_segment(0xDB, b"\x00" + bytes(64))
    out += jpeg_segment(0xC0, b"\x08" + struct.pack(">HH", height, width) + b"\x01\x01\x11\x00")
    out += jpeg_segment(0xC4, b"\x00" + bytes(16))
    out += jpeg_segment(0xDA, b"\x01\x01\x00\x00\x3f\x00")
    out += b"\x12\x34\xff\x00\x56" + b"\xff\xd9" + trailing
    return out


class PngTests(unittest.TestCase):
    def test_valid_png_passes(self):
        r = ic.inspect_image(make_png())
        self.assertEqual((r["content_type"], r["width"], r["height"]), ("image/png", 200, 200))

    def test_text_and_exif_chunks_are_removed(self):
        data = make_png(extra=[(b"tEXt", b"Comment\x00secret"), (b"eXIf", b"GPS-DATA")])
        self.assertIn(b"secret", data)
        cleaned = ic.inspect_image(data)["data"]
        self.assertNotIn(b"secret", cleaned)
        self.assertNotIn(b"GPS-DATA", cleaned)
        self.assertEqual(ic.inspect_image(cleaned)["width"], 200)  # still valid

    def test_damaged_png_is_refused(self):
        data = bytearray(make_png())
        data[40] ^= 0xFF  # break a checksum
        with self.assertRaises(ic.ImageError):
            ic.inspect_image(bytes(data))
        with self.assertRaises(ic.ImageError):
            ic.inspect_image(make_png()[:60])


class JpegTests(unittest.TestCase):
    def test_valid_jpeg_passes(self):
        r = ic.inspect_image(make_jpeg(300, 400))
        self.assertEqual((r["content_type"], r["width"], r["height"]), ("image/jpeg", 300, 400))

    def test_exif_comment_and_trailing_data_are_removed(self):
        data = make_jpeg(trailing=b"HIDDEN-PAYLOAD")
        self.assertIn(b"GPS-LATITUDE", data)
        cleaned = ic.inspect_image(data)["data"]
        for secret in (b"GPS-LATITUDE", b"private comment", b"HIDDEN-PAYLOAD"):
            self.assertNotIn(secret, cleaned)
        self.assertTrue(cleaned.endswith(b"\xff\xd9"))
        self.assertEqual(ic.inspect_image(cleaned)["height"], 200)

    def test_damaged_jpeg_is_refused(self):
        with self.assertRaises(ic.ImageError):
            ic.inspect_image(make_jpeg()[:40])
        with self.assertRaises(ic.ImageError):
            ic.inspect_image(b"\xff\xd8\x00\x00garbage")

    def test_real_jpeg_still_opens_after_cleaning(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed (only used here to build a test picture)")
        buf = io.BytesIO()
        Image.new("RGB", (240, 300), (120, 150, 170)).save(buf, "JPEG", quality=85)
        r = ic.inspect_image(buf.getvalue())
        img = Image.open(io.BytesIO(r["data"]))
        img.load()
        self.assertEqual(img.size, (240, 300))


class LimitTests(unittest.TestCase):
    def test_size_limits(self):
        with self.assertRaises(ic.ImageError):
            ic.inspect_image(make_png(50, 50))
        with self.assertRaises(ic.ImageError):
            ic.inspect_image(make_png(5000, 100))
        with self.assertRaises(ic.ImageError):
            ic.inspect_image(b"x" * (ic.MAX_IMAGE_BYTES + 1))

    def test_other_types_are_refused(self):
        for data in (b"", b"GIF89a....", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", b"%PDF-1.4 x", b"MZ\x90\x00"):
            with self.assertRaises(ic.ImageError):
                ic.inspect_image(data)


if __name__ == "__main__":
    unittest.main()
