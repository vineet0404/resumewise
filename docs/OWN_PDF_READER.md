# Own PDF reader

Status: DONE. `core/extract.py` now uses our own reader; pypdf is removed. This file keeps the design notes. Scanned PDFs are read through Tesseract (`core/ocr.py`), see README.

## Rule for the swap

Only `_pdf_text(data)` in `core/extract.py` changes. It takes bytes and returns text or raises `ExtractError`. The limits (2 MB, 10 pages, password-protected refused, scanned refused) stay the same.

## Build in stages, each stage must pass its tests

1. **File structure.** Find `startxref`, read the cross-reference table, trailer and objects. Fall back to scanning the file for `N 0 obj` when the table is broken.
2. **Streams.** FlateDecode (zlib, standard library), then ASCII85 and LZW. Guard against decompression bombs with a size cap.
3. **Newer PDFs.** Cross-reference streams and object streams (PDF 1.5+).
4. **Page tree and content streams.** Walk Pages to Page to Contents. Read the text operators: BT, ET, Tf, Td, TD, Tm, T*, Tj, TJ, ', ".
5. **Fonts and encodings.** Simple fonts with Encoding and Differences; Type0 / CID fonts with ToUnicode maps. This is where most real-world resumes break, so it needs the most test files.
6. **Layout.** Group characters into lines by position, sort lines, detect two-column pages, keep bullet characters. Output text that `resume_parser` understands.
7. **Edge cases.** Encrypted files (refuse clearly), broken files (clean error, never a crash), huge or recursive structures (limits).

## How we decide it is ready

- Collect 20 to 30 real resume PDFs (with permission or your own), from Word, Google Docs, Canva, LaTeX and online resume builders.
- Write the expected text for each by hand.
- Score pypdf and our reader on the same set (share of lines read correctly).
- Switch only when ours is equal or better, and keep pypdf as a fallback for one release.

## Out of scope

Done separately: scanned PDFs (picture + Tesseract). Still out of scope: JBIG2/CCITT scans, sideways pages, 3+ columns, Type3 bitmap fonts.
