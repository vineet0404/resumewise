# ResumeWise roadmap

Rules: our own code first (no paid tools unless needed), nothing invented in a CV, AI tailoring is tested last.

## Done
1. Login: password, remember me, reset, email verify, magic link, 2FA (authenticator), Google/LinkedIn, passkeys
2. Account hygiene: change password, download my data, delete account
3. Many users at once (load tested), own PDF reader, scanned PDFs (OCR)
4. Build from scratch wizard
5. Jobs tab: job tracker, cover letter, interview practice
6. Mobile version (phone sizes checked; real-phone check is the owner's)
Step 8: Abuse protection + admin dashboard (step 8)
Step 9: Writing help, own code (step 9)
Step 7: Trust pages, feedback button, data explained (text is a draft: lawyer check + fill LEGAL.owner in web/legal.js)
Step 10: Follow-up reminders (daily `send_reminders`; real email arrives with step 12)
Step 12: Deploy kit (Docker, Caddy https, Postgres tested, backups, alerts, health, load test). Needs from you: server, domain, SMTP email; see deploy/README.md
Step 15: Payments with Razorpay Payment Links, Free vs Pro limits. Needs from you: Razorpay account + KYC, test-mode check; see docs/PAYMENTS.md
Step 13: Share link (secret /s/<token>, hides contact/photo by default, owner can turn off) and LinkedIn tips (headline, About, skills, featured, checklist; own code, no AI)
Step 11: Hindi, Marathi, Telugu interface (step 11; translations written by AI, need native-speaker review)

## Next (in this order)
| # | Step | Needs from owner |
|---|------|------------------|
| 14 | **Real AI test** (tailoring, optional bullet feedback and mock interview feedback) | Anthropic key + credit |

## Later (after 50-100 real users)
- College / placement-cell version (one place for 200 students) - likely the best way to earn
- Chrome extension: save a job page into the tracker (user sends the page text, no scraping)
- Live job search and alerts (needs a job-data provider key, e.g. Adzuna or Jooble)
- Portfolio page generated from the CV
- Voice mock interview

## Owner's own to-do
Copy the zip to `E:\ResumeProejct` (Replace all) and run `python manage.py migrate`; Google/LinkedIn keys; Anthropic key; real CVs (typed and scanned); lawyer check; hosting/domain; Razorpay; test with 10 friends before going public.
