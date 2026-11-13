# Payments with Razorpay (step 15)

## How it works (in plain words)
- Two plans: **Free** and **Pro**. Pro is a *pass* for 30 or 90 days (no auto-renew, so nothing to cancel and no mandate problems).
- Free limits (default): 3 AI tailoring runs per day, 10 saved jobs. Pro: the normal limits (`AI_DAILY_PER_USER`, 100 jobs). Building, editing and downloading a CV stays free.
- **Until you set the Razorpay keys, nobody is limited**: everyone has the Pro limits and the Account tab says "Paid plans are not open yet".
- Paying uses a **Razorpay Payment Link**: the person goes to Razorpay's own page and pays by UPI/card/net banking. Card or UPI details never touch our server, and our strict page security rules stay unchanged.
- Our server does three things: asks Razorpay for a link for the exact amount; checks Razorpay's **signed** answer (HMAC-SHA256, own code, no library); switches Pro on. The same payment can never add days twice. If the amount Razorpay took is not the amount we asked for, nothing is switched on (look at it by hand).
- Two ways the answer arrives, so a closed browser tab does not lose a payment: the person is sent back to `/v1/billing/return` (signed), and Razorpay also calls the **webhook** `/v1/billing/webhook` (signed with your webhook secret). Whichever comes first wins.
- A refund (`refund.processed` webhook) removes that pass's days.
- Payment records (date, amount, plan, payment id) stay for accounting after account deletion, without the person's name or email.

## What you must do (owner)
1. Create a Razorpay account and finish KYC (business or individual details, bank account). Razorpay will want the website live with **Terms, Privacy, Refund and Cancellation, and Contact** details: these pages exist (footer links, `backend/web/legal.js`); fill in your name, email, address and get them checked.
2. Dashboard > Account & Settings > API keys: generate **Test** keys first. Dashboard > Webhooks: add `https://YOUR-DOMAIN/v1/billing/webhook`, choose events **Payment Link: paid** (`payment_link.paid`) and **Refund: processed** (`refund.processed`), type a long secret.
3. Set the environment variables (see `deploy/.env.example`): `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, and `SITE_URL=https://YOUR-DOMAIN` (the address Razorpay sends people back to). Restart.
4. **Test in Razorpay test mode** (their test UPI/card details are in their docs): buy a pass with a confirmed-email account, check the Account tab shows Pro, check the payment in the Admin tab numbers, then refund it in the Razorpay dashboard and check Pro goes away. Only then switch to Live keys.
5. Decide prices and free limits: `PRO_30_PRICE_PAISE` (14900 = Rs 149), `PRO_90_PRICE_PAISE`, `FREE_AI_PER_DAY`, `FREE_MAX_JOBS`. Decide the refund rule and edit `legal.js` to match.
6. Ask an accountant about GST (registration, invoices) and income tax. Razorpay emails the customer a receipt, but a GST invoice is your duty. I am not a lawyer or accountant.

## Honest status
All of our side is tested against a local stand-in for Razorpay (request shape, Basic auth, signatures, replay, wrong amount, refund, errors). It has **not** been run against the real Razorpay: the Payment Links field names and the signature recipe are written from Razorpay's documentation, so step 4 above (test mode) is the real proof. If something differs, the fix is small and local (`backend/packs/billing.py`).

## Owner's tools
- Give someone Pro by hand: `python manage.py grant_pro person@example.com 30` (use `0` to switch off).
- Admin tab: payments in the last 30 days, revenue, people on Pro now.
