# ResumeWise (starter)

Resume tailoring that never invents facts. Core logic is plain Python (no packages). The web API uses Django only.

## Web app (sign up, log in, try everything)

Start the server (see Run below) and open `http://127.0.0.1:8000/` in the browser. Sign up with an email and a password (at least 10 characters), then use the three tabs: 1. My CV (upload, edit details and lines, history, delete), 2. Templates and download (preview, scanner check, photo, Word, print to PDF), 3. Tailor to a job (needs the AI key; without it the page says so). It is one HTML page, one script and one stylesheet in `backend/web/`, served by Django itself: no build step, no outside libraries. The page has a strict Content-Security-Policy and never writes user text as markup.

Also new: `GET /v1/profiles` lists your CVs, `DELETE /v1/profiles/<id>` removes a CV with everything linked to it, `GET /v1/profiles/<id>/runs` lists your tailoring results.

## Layout

- `core/` pure Python logic: `redact`, `resume_parser`, `keywords`, `matching`, `tailoring`, `verifier`, `style`, `render`, `ats`, `docx_export`, `image_check`, `gateway`, `providers`, `tailor_service`, `tailored_cv`
- `backend/` Django project (`config/`) and the `packs` app (models, `/v1` API)
- `tests/` core tests (`test_core`, `test_extract`, `test_profile_edit`, `test_style`, `test_image_check`, `test_render`, `test_ats`, `test_quality`, `test_providers`); `backend/packs/tests.py` API tests
- `DEPENDENCIES.md` rules for adding any outside package (read before adding one)

## Run

Use `python -m pip` so pip and python are the same interpreter (Python 3.10 or newer).

Windows (cmd):

```
python -m pip install -r requirements.txt
cd backend
set DEBUG=1
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

PowerShell: use `$env:DEBUG="1"` instead of `set DEBUG=1`.
Linux / Mac: use `export DEBUG=1`.
The variable lasts only for that terminal window.

Try: `GET http://127.0.0.1:8000/v1/health`

## Tests

Run these from the folder that contains `core`, `backend` and `tests`. Type only the command, not the notes.

Core tests (any system):

```
python -m unittest tests.test_core tests.test_extract tests.test_profile_edit tests.test_style tests.test_image_check tests.test_render tests.test_ats tests.test_quality tests.test_providers tests.test_real_cvs
```

API tests, Windows (cmd):

```
cd backend
set DEBUG=1
python manage.py test packs
```

API tests, Linux / Mac:

```
cd backend
DEBUG=1 python manage.py test packs
```

## Settings (environment variables)

| Name | Meaning |
|---|---|
| `DEBUG` | `1` for local work. Leave unset in production. |
| `SECRET_KEY` | Required when `DEBUG` is off. Long and random. |
| `ALLOWED_HOSTS` | Comma separated host names. |
| `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` | Optional LinkedIn sign-in, same idea as Google (see below). |
| `WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGIN` | Passkeys. Leave empty locally and in most setups; set to your domain and `https://` origin if the site sits behind a proxy with another name. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | Optional Google sign-in. Both ID and secret must be set, or the button stays hidden. Redirect URI is optional (derived from the request). |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | Password-reset email. Default prints the email in the server window (fine for testing). For real sending set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` and your SMTP details. |
| `ANTHROPIC_API_KEY` | Key for the hosted AI. Server only; never in code, never in the browser. Without it `/tailor` returns 503. |
| (key check) | A key that does not start with `sk-ant-` or is short gives a clear 503; a key the provider rejects gives a clear 502. |
| `AI_MODEL` | Model id (default `claude-sonnet-5-5`). |
| `AI_PAISE_PER_MTOK_IN`, `AI_PAISE_PER_MTOK_OUT` | Price per million tokens in paise. Fill from the provider price page; the defaults are rough guesses. |
| `BOT_CHECK` | `1` (default) turns on the own bot check on signup and email-link requests (hidden field, minimum wait, small proof-of-work). Set `0` only for load tests. |
| `AI_DAILY_PER_USER` | Max AI tailoring runs per person per 24 hours (default set in settings). Over the limit: 429 `daily_limit`. |
| `AI_DAILY_BUDGET_PAISE` | Max total AI spend in 24 hours for the whole site, in paise. Over it: 503 `budget`. |
| `SIGNUPS_PER_IP_PER_DAY` | Max new accounts from one address per day. |
| `TIME_ZONE` | Zone used for "today" in follow-up reminders (default `Asia/Kolkata`). Times are still stored in UTC. |
| `ALERT_EMAIL`, `CSRF_TRUSTED_ORIGINS`, `BACKUP_DIR`, `BACKUP_KEEP_DAYS`, `LOG_LEVEL` | Deploy (step 12): who is emailed when the server breaks; extra https origins; backup folder and days kept; log detail. See `deploy/README.md`. |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `SITE_URL`, `PRO_30_PRICE_PAISE`, `PRO_90_PRICE_PAISE`, `FREE_AI_PER_DAY`, `FREE_MAX_JOBS` | Payments (step 15). Without keys, nobody is limited. See `docs/PAYMENTS.md`. |
| `DATABASE_URL` | `sqlite:///db.sqlite3` (default), `postgres://user:pass@host:5432/db`, `oracle://...`, `mssql://...` |

Oracle and SQL Server need their own Django driver installed and a full test run on that database before you rely on them.

## API (v1)

All endpoints except `health` need a signed-in user.

- `GET /v1/health`
- `GET /v1/auth/csrf` returns a token; send it as the `X-CSRFToken` header on every POST
- `POST /v1/auth/register` with `name`, `email`, `password`, `accept_terms: true`; `POST /v1/auth/login` with `email`, `password`, optional `remember` (default true: 30 days; false: ends when the browser closes); `POST /v1/auth/logout`; `GET /v1/auth/me`
- `GET /v1/auth/providers` says which sign-in options are on (`google`, `linkedin`, `passkeys`); `GET /v1/auth/google/start` and `/callback` are the browser steps of Google sign-in (see below)
- `POST /v1/auth/verify/send` (signed in) and `POST /v1/auth/verify` with `token`: confirm email. Link `/#verify=TOKEN`, 3 days, once. AI tailoring returns 403 `email_not_verified` until confirmed (accounts made before this feature count as confirmed)
- `POST /v1/auth/magic/send` with `email` and `POST /v1/auth/magic` with `token`: passwordless login link, 15 minutes, once. Same answer for unknown emails
- Two-step (authenticator app, RFC 6238): `POST /v1/auth/2fa/setup`, `/2fa/enable` (returns 8 recovery codes once), `/2fa/disable`, `/2fa/recovery` (new codes), all signed in and with `code`. A login (password, magic link, Google, LinkedIn) then answers `{"needs_2fa": true}` and you finish with `POST /v1/auth/2fa/verify` `code` (5 tries, 5 minutes, a code works once)
- Passkeys: `POST /v1/auth/passkey/register/options` then `/passkey/register` (signed in); `POST /v1/auth/passkey/login/options` then `/passkey/login`; `GET /v1/auth/passkeys`; `DELETE /v1/auth/passkeys/<id>`. A passkey login skips the 2-step code (it is already two factors)
- Account hygiene (signed in): `POST /v1/auth/password` (`new`, plus `current` if the account has a password; signs out other devices; a Google/LinkedIn-only account can set a first password without `current`); `GET /v1/me/export` downloads all your data as JSON (never passwords, 2-step secrets or recovery codes); `POST /v1/auth/delete` (`confirm_email`, plus `password` and/or `code` when the account has them) removes the account and everything under it. All three are rate limited (5 per 15 minutes for password/export, 5 wrong delete tries)
- `POST /v1/auth/2fa/setup` also returns `qr`: rows of "0"/"1" for a QR code of the setup link, made by our own encoder (`packs/qr.py`, byte mode, error level L, up to about 520 characters). The web app draws it as SVG
- `POST /v1/auth/forgot` with `email` always answers the same (no account probing), at most 3 emails per address per 15 min; `POST /v1/auth/reset` with `uid`, `token`, `password` (link works once, 1 hour). The email link is `/#reset=UID.TOKEN`; the token is after `#` so it stays out of server logs
- `POST /v1/match` with `resume_text`, `job_text` returns score, covered and missing terms
- `POST /v1/profiles` with `resume_text` stores a parsed resume (auto-deleted after 30 days)
- `POST /v1/profiles/upload` form field `file` (PDF, DOCX or TXT, max 2 MB, PDFs up to 10 pages); the file is not stored, only the parsed text. The response also has `ats` (score and findings for the uploaded file)
- `GET /v1/profiles/<id>` returns your own profile only; others get 404

### Update my CV

All need login and CSRF header; only your own profile (others get 404).

- `PATCH /v1/profiles/<id>/contact` with any of `name`, `email`, `phone`, `location`, `links` (empty string clears). The name is guessed from the top of the CV (the first plain 2 to 4 word line that is not an address or title); fix it here if the guess is wrong
- `POST /v1/profiles/<id>/items` with `section`, `text` adds a line (new lines get new ids that are never reused)
- `PATCH /v1/profiles/<id>/items/<item_id>` with `text`; `DELETE` the same URL removes it
- `GET /v1/profiles/<id>/versions` lists the last 20 saved versions
- `POST /v1/profiles/<id>/versions/<version_id>/restore` undoes back to that version

Each change saves the old CV as a version first. Any change also restarts the 30-day retention timer.

### Templates and photo

Login and CSRF needed; only your own profile (others get 404).

- `GET /v1/templates` lists 5 templates: classic, modern, compact (no photo), photo_header, photo_sidebar (with photo; two columns, higher scanner risk; the side bar holds only the photo and contact, everything else is in the main column)
- `PATCH /v1/profiles/<id>/template` with `template`
- `POST /v1/profiles/<id>/photo` form field `photo` (JPEG or PNG, 1 MB, 100 to 4000 px); `DELETE` removes it
- `GET /v1/profiles/<id>/render?template=<id>` returns the finished resume as an HTML page (print it to PDF from the browser)
- `GET /v1/profiles/<id>/ats?template=<id>` returns `score` (0 to 100) and `findings` (error, warn, info) for how a simple text scanner reads your CV

Photo rules: file type is read from the bytes; location and camera data are stripped (`core/image_check.py`, our own code); the photo is never sent to AI; it is deleted with the CV after 30 days or when you remove it. All resume text is escaped and the preview page has a strict Content-Security-Policy.

### AI tailoring (hosted API)

- `POST /v1/profiles/<id>/tailor` with `job_text` (max 8000 chars) and optional `job_title`. Limit: 10 runs per user per 15 minutes.
- What goes to the AI: only the numbered resume lines and the job text, with emails, phones, links and your name replaced by placeholders. The header (name, contact) and the photo are never sent. Nothing is logged except a short error message.
- What comes back is checked by our own code: JSON shape, every line must point to a real source line, then the verifier labels each line supported, reworded or new (numbers or tools not in your CV become new), then style checks. The AI cannot approve its own lines.
- Stored: a Job, Run, Output and one Claim per line, deleted with the CV (30 days).
- Cost: the gateway stops a run at the cost cap. Rates are settings, see the table above.
- Only tested against a local fake server. Before real users: run it once with your real key and read the output yourself.

### Review and export a tailored CV

Login and CSRF needed; only your own runs (others get 404). Use the `run_id` from the tailor response.

- `GET /v1/runs/<id>` every line with `label` (supported, reworded, new), `reason`, `decision`, plus `pending` and `can_export`
- `PATCH /v1/runs/<id>/claims/<line_ref>` with `decision`: `confirmed`, `removed` or `pending`
- `GET /v1/runs/<id>/render?template=<id>`, `GET /v1/runs/<id>/ats`, `GET /v1/runs/<id>/export?format=docx`: return 409 with the list of `pending` lines until every new line is confirmed or removed

Name and contact details always come from your own CV, never from the AI. Removed lines are left out. Supported and reworded lines need no decision (you can still remove them).

### Try the review screens without AI

With `DEBUG=1`: `python manage.py demo_run <profile_id>` makes a demo run from your CV (one line gets an invented number so you can practise confirm and remove) and prints `run_id`. Put it in Postman's `run_id` variable. Local testing only; it refuses to run when `DEBUG` is off.

### Upload and download quality

- Upload: PDF text is cleaned (ligatures like fi, odd spaces, control characters) and lines broken only by page width are joined back (bullets, headings and short lines never joined; dates split after a dash are rejoined). A CONTACT block goes to the header. All 5 template PDFs read back with the same sections and item counts as the source.
- Download Word: `GET /v1/profiles/<id>/export?format=docx` (own code, `core/docx_export.py`). One column, real heading styles and bullets, no tables, no photo. Opened and checked in LibreOffice; special characters are escaped. PDF: print the `/render` page from the browser.
- Word files: shapes and text boxes are read once (not twice), each text box line stays a separate line, and the page header (often the contact details) is included. Footers are skipped.
- Known limits: two-column PDFs with narrow columns can still break lines oddly; scanned PDFs need Tesseract installed (see "Scanned PDFs (OCR)"); the Word file has no photo.

### Scanner (ATS) check

`core/ats.py` turns the CV into a PDF-like text reading order and checks: name first, standard headings, email and phone near the top, no spaced-out headings, no icons, length. We tested all 5 templates by printing to PDF in Chromium and reading the text back with pypdf; that found and fixed spaced headings (Classic) and wrong reading order (photo sidebar). No real company ATS was tested, so treat the score as "no obvious problems", not a guarantee.

## Tailoring rules

See `docs/TAILORING_RULES.md`: only the user's facts, minimal change, no stock phrases, the user's own style.

## Share link and LinkedIn tips

Templates tab > "Share your CV with a link" makes a secret address `/s/<token>` (24 random bytes). Anyone with the address can read the CV; email, phone and photo are hidden unless the owner ticks them. The page sends `noindex`, `no-referrer`, `X-Frame-Options: DENY`, a strict CSP and `no-store`; only a view counter is kept. Wrong guesses are throttled per IP (429). The link dies when it is turned off, when the CV expires (30 days) or is deleted. My CV tab > "LinkedIn profile tips" (`core/linkedin.py`) builds headline options, an About draft, skills, featured projects and a checklist from CV lines only: no AI, nothing invented. API: `GET/PUT/DELETE /v1/profiles/<id>/share`, `GET /v1/profiles/<id>/linkedin?target=`. Run `python manage.py migrate` (0010).

## Postman

Import `docs/ResumeWise.postman_collection.json`. Run "Get CSRF token" first, then Register or Login.

## PDF reader plan

PDFs are read by our own pure-Python reader (no pypdf): `core/pdfread.py` (file structure, streams), `pdffonts.py` (fonts, ToUnicode), `pdftext.py` (text positions, two-column order), `pdfimage.py` (scan pictures). Design notes: `docs/OWN_PDF_READER.md`.

### Build from scratch (wizard)

For a user with no CV: tab "1. My CV" has "Build my CV from scratch". Eight screens (details, summary, education, skills, projects, experience, more, check) each with grey example hints, then "Create my CV". The answers go to `POST /v1/profiles/build` (JSON: `contact`, `role`, `summary`, `education[]`, `skills[]`, `projects[]`, `experience[]`, `certifications`, `achievements`, `languages`). `core/cv_builder.py` turns them into the same structure an uploaded CV has, so templates, ATS check, line editing, history, Word download and tailoring all work. Nothing is invented: every line is what the person typed, joined with " | ". Limits: 6 education, 8 projects, 8 jobs, 8 points each, 15 lines in the extra lists. The typed answers stay in the browser tab only until "Create my CV".

See `docs/ROADMAP.md` for what is done and what comes next.

### Phones

Works from 320 px wide. Tap targets are 44 px on touch screens, inputs are 16 px (iPhone does not zoom in), the five tabs scroll sideways in one row, the wizard keeps Back/Next at the bottom of the screen, and the CV preview shows the whole A4 sheet scaled down instead of cropped. Check with `python tests/mobile_audit.py 360` (see the file header). Real-phone check is still on you: open the site on your phone over the same Wi-Fi (`python manage.py runserver 0.0.0.0:8000`, then http://<your PC IP>:8000; set `ALLOWED_HOSTS` if Django refuses).

### Jobs tab: job tracker, cover letter, interview practice

Tab "4. Jobs" (Account moved to 5). All our own code, no AI, no cost, nothing invented.
- Save a job: title, company, optional link (http/https only), pasted job description (8000 characters). Max 100 jobs per person. The score is `core/job_match.py` (same scoring as the match check) against the CV open in the app; each matched word shows the CV line that proves it, and missing words are listed with "add only if true".
- Status: saved, applied, interview, offer, rejected. Notes up to 4000 characters.
- Cover letter (`core/cover_letter.py`): quotes up to 4 real CV lines that match the job, the education line, and the person's own paragraph. A required skill the CV does not show is never mentioned (it is listed as "left out"). Editable, Copy, Download .txt.
- Interview practice (`core/interview.py`): up to 14 questions (intro, why this job, one per matched skill with the CV line, one per missing required skill with "be honest, never claim it", two "walk me through this CV line", behaviour questions). Answers are saved per job.
- API: `GET/POST /v1/jobs`, `GET/PATCH/DELETE /v1/jobs/<id>` (GET takes `?profile_id=`), `POST /v1/jobs/<id>/cover-letter`, `GET/PUT /v1/jobs/<id>/interview`. Jobs follow the 30-day rule (`purge_expired`) and are in "Download my data".
- Not built: a live job search. That needs a job-data provider (for example Adzuna or Jooble, with an API key) because scraping job sites breaks their terms. Until then, people paste the description from the site.

### Scanned PDFs (OCR)

A page with almost no text and a big picture is a scan. We take the picture out of the PDF and give it to Tesseract (free, runs on your own machine, nothing is sent anywhere). The upload response then has `"ocr": true` and the screen asks the user to check every line.

- Install: Windows: UB Mannheim Tesseract installer (default folder is found automatically, or set `TESSERACT_PATH`). Linux: `apt install tesseract-ocr`.
- Env: `OCR_ENABLED=0` turns it off, `OCR_LANGS=eng` (e.g. `eng+hin` after installing that language data), `OCR_TIMEOUT=45` seconds, `OCR_MAX_CONCURRENT=2` (extra scans get HTTP 503 "try again").
- Only the first 3 scanned pages are read. Run gunicorn with `--timeout 120` so a slow scan is not killed.
- Not supported: fax-style scans (JBIG2/CCITT, some office scanners), sideways pages, handwriting, 3+ columns, PDFs whose fonts are garbled and have no picture, Type3 bitmap-font PDFs (some LaTeX). They give a clear error.

### Languages (English, Hindi, Marathi, Telugu)
A language box sits at the top of every screen; the choice is remembered in the browser. The texts are in `backend/web/i18n.js` (generated from `tools_i18n_data.py`: edit that file, then run `python3 tools_i18n_data.py`). Unknown texts simply stay English. **The translations were written by an AI and must be checked by a native speaker before launch.** Your CV text is never translated, and the writing tips (step 9) still check English lines only. DOCX/PDF output in Hindi/Marathi/Telugu text is untested (fonts).

### Deploy kit (step 12) and payments (step 15)
`deploy/` has a Dockerfile, docker-compose (app + PostgreSQL + Caddy for automatic https), `.env.example`, a daily-jobs crontab and an uptime check; `deploy/README.md` is the step-by-step. Commands: `backup` (SQLite or PostgreSQL, keeps 14 days), `purge_expired`, `send_reminders`, `grant_pro`. `/v1/health` returns 503 when the database is down. Server errors email `ALERT_EMAIL` (one per kind per 10 minutes). The whole test suite also passes on PostgreSQL 16 (`DATABASE_URL=postgres://...` then `python manage.py test packs`). `python tests/loadtest.py URL --users 100` load-tests your own server. Payments (Razorpay Payment Links, Free vs Pro limits): `docs/PAYMENTS.md`.

### Trust pages and feedback (step 7)
Terms of Use, Privacy Policy, Refund and Cancellation and Questions-and-answers open from the footer, the sign-up screen and the Help tab, and by link: `/#terms`, `/#privacy`, `/#faq`. Their text is in `backend/web/legal.js`. **It is a draft written to match what the app really does; a lawyer must check it, and you must fill `LEGAL.owner` (name, email, place) before launch.** The legal texts are English only. The Help tab also has a "Send feedback" form (`POST /v1/feedback`, max 10 a day per person, shown to staff in the Admin tab, deleted with the account) and a plain-words data summary.

### Follow-up reminders (step 10)
Marking a job as *applied* sets the applied day and suggests a follow-up 7 days later. In the Jobs tab the person can change the day, snooze (3 or 7 days) or switch the email off per job; due jobs show in a "Time to follow up" box (`GET /v1/jobs/due`). Run **once a day**: `python manage.py send_reminders` (`--dry-run` to preview). It sends one email per person (job title and company only), only to confirmed emails, each reminder once (a new follow-up day arms it again). Real sending needs the email settings (step 12); until then the email is printed in the server window.

### Admin, abuse protection, writing help
- `python manage.py make_staff you@example.com` makes a staff account; it sees an **Admin** tab (users, CVs, runs, spend, recent errors; no CV text).
- Bot check, per-user and per-day AI limits: see the settings table. Errors are stored without what the person typed and purged after 30 days (`purge_expired`).
- Writing help: each CV line gets tips (weak start, too short, no number...) that only ask questions; the **Help** tab has the fresher guide and checklist.

## Retention

Run `python manage.py purge_expired` every night (cron or scheduler).

## Not built yet

Password reset, email verification, server-side PDF export, editing the text of a tailored line before confirming it, job finder, front end.


## Sign in with Google (optional)

Own code, no OAuth library (`backend/packs/google_auth.py`). Off until you set the two keys.

1. Open Google Cloud Console, create a project, then APIs and Services, OAuth consent screen (External, add your own email as a test user while testing).
2. Credentials, Create credentials, OAuth client ID, type **Web application**.
3. Under "Authorized redirect URIs" add exactly: `http://127.0.0.1:8000/v1/auth/google/callback` (for a real site, your https address plus the same path).
4. Copy the Client ID and Client secret, then in the window where the server runs:
   - Windows cmd: `set GOOGLE_CLIENT_ID=...` and `set GOOGLE_CLIENT_SECRET=...`, then `python manage.py runserver`
5. Reload the page: "Continue with Google" appears on Sign up and Log in.

How it stays safe: a random `state` and `nonce` are kept in the session and checked on return; the code is swapped for the token by this server talking to Google over HTTPS; the token must be for your client ID, from Google, not expired, with a verified email. A Google user with the same email as an existing account signs in to that account. The secret stays on the server and is never sent to the browser.


## Sign in with LinkedIn (optional)

Same code as Google (`backend/packs/social_auth.py`).

1. LinkedIn Developer Portal, Create app (needs a LinkedIn Page for your company or project).
2. Products tab: add **Sign In with LinkedIn using OpenID Connect**.
3. Auth tab: add the redirect URL `http://127.0.0.1:8000/v1/auth/linkedin/callback`, copy Client ID and Primary Client Secret.
4. `set LINKEDIN_CLIENT_ID=...` and `set LINKEDIN_CLIENT_SECRET=...`, restart the server. "Continue with LinkedIn" appears.

## Email confirm, magic link, two-step, passkeys

- **Email confirm**: sign-up emails a one-time link. Until it is used, the Account tab and a banner say "not confirmed" and AI tailoring is blocked (it costs money). Links carry the token after `#`, so it never reaches server logs. Only a SHA-256 hash of each token is stored.
- **Magic link**: "Email me a login link instead" on the login page. Using it also confirms the email.
- **Two-step (authenticator app)**: Account tab, Set up. No QR code yet: type the setup key into Google Authenticator, Microsoft Authenticator or Authy (on a phone, the "Open it in your authenticator app" link adds it directly). The secret is stored encrypted with a key derived from `SECRET_KEY`, so keep that key safe and stable. Recovery codes are stored only as hashes.
- **Passkeys**: Account tab, Add a passkey. Uses ES256 only (all current phones, Windows Hello and password managers). The server checks real WebAuthn answers with its own CBOR reader and P-256 signature check (`backend/packs/webauthn.py`), tested against RFC 6979 and cross-checked with the `cryptography` library in the tests (the library is not needed to run the app).
  - **Locally open the site as `http://localhost:8000`, not `127.0.0.1`**: browsers refuse passkeys on a bare IP address. Phones need your real `https://` domain, so phone passkeys are testable after deploy.
  - Login finds the passkey on the device (no email typed first), so old non-resident hardware keys without discoverable credentials will not work for login.

Sign-in logic lives in one place (`finish_login` in `auth_views.py`): every method goes through it, so two-step is never skipped by accident (only a passkey skips it, on purpose).


## Many users at once (load and crashes)

`manage.py runserver` is for your own computer only. For real users run a production server with several worker
processes, so one slow request or one crash never stops everyone else.

Windows (your laptop or a Windows server): `pip install waitress`, then from the `backend` folder
`waitress-serve --listen=127.0.0.1:8000 --threads=8 config.wsgi:application`

Linux server: `pip install gunicorn`, then `gunicorn config.wsgi:application -b 127.0.0.1:8000 -w 4 --threads 4 --timeout 120`
(rule of thumb: workers = CPU cores, 4 threads each). Put nginx (or any load balancer) in front for https, static
caching and, later, several servers.

Settings that matter when more than one person or more than one process is involved:

| Setting | What it does |
|---|---|
| `DATABASE_URL` | SQLite is fine for a few users (it is tuned: waits up to 20 s for a write lock, WAL mode). For real traffic use Postgres: `postgres://user:pass@host:5432/resumewise` |
| `CACHE_BACKEND=db` | Needed with more than one worker process, so the "too many attempts" counters are shared. Run `python manage.py createcachetable` once |
| `TRUSTED_PROXIES` | Number of proxies / load balancers in front of Django (nginx = 1). Without it every visitor looks like the proxy's address. Leave `0` when nothing is in front |
| `IP_LIMIT_MULTIPLIER` | Default 5. One address can be a whole college, so per-address limits (sign-ups, failed logins) are 5 times the per-person limit. Per-account limits (5 wrong passwords per email) stay strict |
| `AI_MAX_CONCURRENT` | Default 4. Most AI calls running at once in one process. More callers get HTTP 503 `busy` with `Retry-After`, instead of everything slowing down |

What was measured (SQLite, one laptop-class machine, gunicorn 4 workers x 4 threads): 100 people at the same time, each
signing up, saving a CV, reading it, downloading their data, logging out and in again (1200 requests): no failures,
no "database is locked". The slowest part is password hashing (on purpose), which is why more worker processes help.

Not done yet: a real load test on the deployed server, database backups, and a status/health check for the load balancer
(`/v1/health` already exists and can be used for it).
