# Dependency policy

Rule: write our own code for anything that is our product's value. Use a library only where writing it ourselves would be slower, less secure, or wrong.

## Build ourselves (our own code, in `core/`)

| Area | Why we own it |
| --- | --- |
| Redaction of personal details before AI calls | Core privacy promise |
| Resume section parser (rule-based first) | Core product logic |
| Keyword extraction and match scoring | Core product logic, easy to test |
| Tailoring output validation (source ids, schema) | The truthfulness promise |
| Claim verifier rules (Supported / Reworded / New) | The truthfulness promise |
| AI gateway (model routing, cost cap, retries) | Lets us swap API for our own model later |
| Database URL parsing and settings | Small, avoids a package |

## Use a trusted library (do not write ourselves)

| Need | Choice | Why not build |
| --- | --- | --- |
| Web framework, ORM, auth, migrations | Django | Security-critical, huge surface, supports PostgreSQL and Oracle, SQL Server via mssql-django |
| Password hashing, TLS, encryption primitives | Django built-ins and the `cryptography` package (add when field encryption is built) | Never write your own cryptography |
| Reading text from scanned PDFs (OCR) | Tesseract (separate program, optional, Apache 2.0) | A good recogniser needs years of training data; we call it, we do not copy it |
| Reading and writing DOCX | python-docx (add in the export step) | Same |
| Payments | Razorpay Payment Links (hosted page); our own small client and signature check in `packs/billing.py`, no Razorpay library | Card data must never touch our servers; the API is two calls, so no SDK needed |
| Production web server | gunicorn (`requirements-prod.txt`) | Mature, we do not write servers |
| PostgreSQL driver | psycopg 3 (`requirements-prod.txt`, only when `DATABASE_URL` is postgres) | Database driver |

## Rules for adding any new dependency

1. Write down in this file what it does and why we cannot reasonably build it.
2. Check its licence allows commercial use.
3. Check it is actively maintained and widely used.
4. Pin the exact version.
5. Prefer the standard library when it is enough.

## Current third-party packages

- Django
- No PDF package. PDFs are read by our own code (`core/pdfread.py`, `pdffonts.py`, `pdftext.py`, `pdfimage.py`).

## Optional program (not a Python package)

- Tesseract OCR: only used for scanned PDFs (`core/ocr.py`). Without it, text PDFs work as normal and a scanned PDF gets a clear message. Install: Windows from the UB Mannheim installer, Linux `apt install tesseract-ocr`.

## Test-only helper (not installed in production)

- Pillow: used only by one test in `tests/test_image_check.py` to build a real JPEG. The test is skipped when Pillow is missing. Nothing in `core/` or `backend/` imports it.
