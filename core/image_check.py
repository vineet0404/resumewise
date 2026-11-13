"""Check and clean a profile photo. Standard library only (no image package).

Accepts JPEG and PNG. The type is decided by the file's own bytes.

Cleaning:
- JPEG: keeps only the parts needed to show the picture. Camera data (EXIF, GPS
  location, thumbnails, comments) is removed. Anything after the end marker is cut.
- PNG: keeps only the critical parts. Text and EXIF chunks are removed. Animation
  data is dropped, so an animated PNG becomes its first frame.

This does not resize or re-encode the picture, so quality is unchanged.
"""

import struct
import zlib

MAX_IMAGE_BYTES = 1024 * 1024
MIN_SIDE = 100
MAX_SIDE = 4000
MAX_PNG_CHUNKS = 5000

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_KEEP = (b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS")
# JPEG segments we keep: quantisation tables, Huffman tables, restart interval,
# arithmetic conditioning, Adobe colour flag, and every start-of-frame marker.
_JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
_JPEG_KEEP = {0xDB, 0xC4, 0xDD, 0xCC, 0xEE} | _JPEG_SOF


class ImageError(ValueError):
    """The picture cannot be used. The message is safe to show to the user."""


def inspect_image(data):
    """Return {"content_type", "width", "height", "data"} with the cleaned bytes."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ImageError("the photo is empty")
    data = bytes(data)
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError("the photo is too large (limit 1 MB)")
    if data[:8] == PNG_SIGNATURE:
        result = _clean_png(data)
    elif data[:2] == b"\xff\xd8":
        result = _clean_jpeg(data)
    else:
        raise ImageError("upload a JPEG or PNG photo")
    width, height = result["width"], result["height"]
    if min(width, height) < MIN_SIDE:
        raise ImageError("the photo is too small (at least %d pixels on each side)" % MIN_SIDE)
    if max(width, height) > MAX_SIDE:
        raise ImageError("the photo is too large (at most %d pixels on each side)" % MAX_SIDE)
    return result


def _clean_png(data):
    out = bytearray(PNG_SIGNATURE)
    i = len(PNG_SIGNATURE)
    n = len(data)
    width = height = None
    seen_idat = seen_iend = False
    chunks = 0
    while i + 8 <= n:
        chunks += 1
        if chunks > MAX_PNG_CHUNKS:
            raise ImageError("this PNG file is not valid")
        length = struct.unpack(">I", data[i:i + 4])[0]
        ctype = data[i + 4:i + 8]
        end = i + 8 + length + 4
        if end > n:
            raise ImageError("this PNG file is damaged")
        body = data[i + 8:i + 8 + length]
        crc = struct.unpack(">I", data[end - 4:end])[0]
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != crc:
            raise ImageError("this PNG file is damaged")
        if chunks == 1:
            if ctype != b"IHDR" or length != 13:
                raise ImageError("this PNG file is not valid")
            width, height = struct.unpack(">II", body[:8])
        if ctype in _PNG_KEEP:
            out += data[i:end]
        if ctype == b"IDAT":
            seen_idat = True
        if ctype == b"IEND":
            seen_iend = True
            break
        i = end
    if width is None or not seen_idat or not seen_iend:
        raise ImageError("this PNG file is damaged")
    return {"content_type": "image/png", "width": width, "height": height, "data": bytes(out)}


def _clean_jpeg(data):
    n = len(data)
    out = bytearray(b"\xff\xd8")
    i = 2
    width = height = None
    reached_scan = False
    while i < n:
        if data[i] != 0xFF:
            raise ImageError("this JPEG file is damaged")
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            break
        marker = data[i]
        i += 1
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0xD8:
            continue
        if marker == 0xD9:
            break
        if i + 2 > n:
            raise ImageError("this JPEG file is damaged")
        length = struct.unpack(">H", data[i:i + 2])[0]
        if length < 2 or i + length > n:
            raise ImageError("this JPEG file is damaged")
        segment = data[i:i + length]
        if marker in _JPEG_SOF:
            if length < 8:
                raise ImageError("this JPEG file is damaged")
            height, width = struct.unpack(">HH", segment[3:7])
        if marker == 0xDA:
            if width is None:
                raise ImageError("this JPEG file is damaged")
            rest = data[i + length:]
            last_end = rest.rfind(b"\xff\xd9")
            if last_end < 0:
                raise ImageError("this JPEG file is damaged")
            out += b"\xff\xda" + segment + rest[:last_end + 2]
            reached_scan = True
            break
        if marker in _JPEG_KEEP:
            out += bytes([0xFF, marker]) + segment
        i += length
    if not reached_scan or not width or not height:
        raise ImageError("this JPEG file is damaged")
    return {"content_type": "image/jpeg", "width": width, "height": height, "data": bytes(out)}
