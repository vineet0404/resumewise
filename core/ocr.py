"""OCR: reading text from a picture of a page.

We do not write our own recogniser (that is a research project of its own and would be far less accurate).
This file calls Tesseract, a free engine that runs on your own machine or server, so the CV never leaves
it. If Tesseract is not installed, `available()` is False and the app says so politely.

Settings (environment variables):
  OCR_ENABLED         auto (default) | 0 | 1
  TESSERACT_PATH      full path to tesseract(.exe) if it is not on PATH
  OCR_LANGS           e.g. eng or eng+hin (the language data must be installed)
  OCR_MAX_CONCURRENT  how many OCR jobs may run at once in this process (default 2)
  OCR_TIMEOUT         seconds per page (default 45)
"""

import os
import shutil
import subprocess
import threading

_SLOTS = threading.BoundedSemaphore(max(1, int(os.environ.get("OCR_MAX_CONCURRENT", "2"))))
_LANG_OK = {c for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_+"}


class OcrError(ValueError):
    """OCR failed. The message is safe to show."""


class OcrBusy(OcrError):
    """Too many OCR jobs are running right now."""


def _path():
    if os.environ.get("OCR_ENABLED", "auto").strip().lower() in ("0", "false", "no", "off"):
        return None
    explicit = os.environ.get("TESSERACT_PATH", "").strip()
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    found = shutil.which("tesseract")
    if found:
        return found
    for guess in (r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if os.path.isfile(guess):
            return guess
    return None


def available():
    return _path() is not None


def _lang():
    lang = os.environ.get("OCR_LANGS", "eng").strip() or "eng"
    return lang if all(c in _LANG_OK for c in lang) else "eng"


def read_image(image_bytes, dpi=None):
    """Text found in an image file (JPEG/PNG), or raise OcrError."""
    exe = _path()
    if exe is None:
        raise OcrError("OCR is not installed on this server")
    if not _SLOTS.acquire(blocking=False):
        raise OcrBusy("too many scans are being read right now; please try again in a minute")
    try:
        cmd = [exe, "stdin", "stdout", "-l", _lang(), "--psm", "1"]
        if dpi:
            cmd += ["--dpi", str(int(max(70, min(600, dpi))))]
        env = dict(os.environ, OMP_THREAD_LIMIT="1")
        try:
            done = subprocess.run(cmd, input=image_bytes, capture_output=True, timeout=float(os.environ.get("OCR_TIMEOUT", "45")), env=env)
        except subprocess.TimeoutExpired:
            raise OcrError("reading the scan took too long")
        except OSError:
            raise OcrError("OCR could not be started")
        if done.returncode != 0:
            raise OcrError("the scan could not be read")
        return done.stdout.decode("utf-8", "replace")
    finally:
        _SLOTS.release()
