# Putting ResumeWise on the internet (step 12)

What is already done and tested here: the whole test suite passes on **PostgreSQL 16**; the production server (gunicorn, DEBUG off,
Postgres, shared counters, behind a proxy header) served 100 people / 1200 requests with no errors; https redirect, HSTS and
secure cookies are on when DEBUG is off; backups and restore work on SQLite and PostgreSQL; `/v1/health` checks the database.
What is **not** tested here (no server, domain or Docker daemon): the Docker files, Caddy's certificate, real email sending, and
your hosting provider. Follow the steps and fix anything that surprises you.

## What you need (owner)
1. A small Linux server (VPS) in India if most users are there, 2 GB RAM is enough to start. Examples: AWS Lightsail Mumbai, DigitalOcean Bangalore, Hetzner (EU), any provider.
2. A domain name, with an **A record** pointing to the server's IP address.
3. An email sending service with SMTP (Brevo, Amazon SES, Zoho, Gmail SMTP for a small start). Without it, login links, confirmation, reset and reminder emails cannot be sent.
4. Optional now: Anthropic API key (AI), Google/LinkedIn keys, Razorpay keys (see docs/PAYMENTS.md).

## Steps (Docker, easiest)
1. On the server install Docker (docker.com, "Install Docker Engine"). Copy the project folder there.
2. `cp deploy/.env.example deploy/.env` and fill it: `DOMAIN`, `DB_PASSWORD` (long random), `SECRET_KEY` (50 random characters; **never change it later**, two-step secrets depend on it), `ALLOWED_HOSTS` (your domain), email settings, `ALERT_EMAIL`.
3. `docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build`
4. First time only, inside the app container:
   - `docker compose -f deploy/docker-compose.yml exec app python manage.py migrate`
   - `docker compose -f deploy/docker-compose.yml exec app python manage.py createcachetable`
   - `docker compose -f deploy/docker-compose.yml exec app python manage.py make_staff you@example.com` (after you sign up on the site; gives you the Admin tab)
5. Open `https://your-domain`. Caddy gets the certificate by itself (ports 80 and 443 must be open).
6. Add the daily jobs from `deploy/crontab.example` (purge expired data, backup, reminders).
7. Fill the owner details in `backend/web/legal.js` and get the Terms/Privacy/Refund text checked by a lawyer (see README).

## Without Docker
`pip install -r requirements-prod.txt`, set the same environment variables, `python manage.py migrate`, `createcachetable`, then
`gunicorn config.wsgi:application -b 127.0.0.1:8000 -w 4 --threads 4 --timeout 120` behind nginx or Caddy (https, `TRUSTED_PROXIES=1`).
For OCR install Tesseract (`apt install tesseract-ocr tesseract-ocr-hin tesseract-ocr-mar tesseract-ocr-tel`).

## Backups (do not skip)
- `python manage.py backup` writes a file into `BACKUP_DIR` (default 14 days kept). Run it daily (crontab).
- **Copy the backups off the server** (another machine, or object storage); a backup on the same disk dies with the disk.
- Backups contain everyone's data: keep them private, and keep `BACKUP_KEEP_DAYS` at 30 or less so deleted data really goes.
- Check a file: `python manage.py backup --verify backups/FILE`. **Practise a restore once** before you need it:
  - PostgreSQL: create an empty database, then `pg_restore -d NEWDB --no-owner FILE.dump`
  - SQLite: stop the app, replace the `.sqlite3` file with the backup, start the app.

## Watching the site
- **Errors**: set `ALERT_EMAIL`; a server error sends one email (not more than one per kind per 10 minutes). The Admin tab lists the latest.
- **Down?** Point a free uptime service (UptimeRobot, Better Stack) at `https://your-domain/v1/health` (200 = fine, 503 = database down), or run `python deploy/uptime_check.py https://your-domain` from another machine with cron.
- **Load test your own server**: start it once with `BOT_CHECK=0` and a high `SIGNUPS_PER_IP_PER_DAY`, then from your laptop `python tests/loadtest.py https://your-domain --users 100 --threads 25` (add `--forwarded` only for a local test server). Delete the `loadtest-*@example.com` accounts afterwards and switch the bot check back on.

## Measured here (not your server)
100 people at once, 1200 requests: 0 errors, median 229 ms, 95% under 1.5 s, on a small shared machine with Postgres and 4 workers x 4 threads. Most of the time is password hashing on purpose. Re-measure on your real server.
