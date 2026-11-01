# Breatheasy launch checklist

Work top to bottom. Items marked **(blocking)** must be done before sharing the link publicly.

## 1. Google Cloud (about 30 minutes, mostly waiting)

- [ ] **(blocking)** Billing account attached to the project.
- [ ] **(blocking)** Run `./deploy/cloudrun/setup.sh` in Cloud Shell. It enables APIs, creates the database, the API keys and the secrets. Keys never need to be pasted into chat or committed anywhere.
- [ ] **(blocking)** Budget alert: Console → Billing → Budgets & alerts → create a monthly budget (e.g. ₹3,000) with email alerts at 50%, 90%, 100%.
- [ ] **(blocking)** Per-API daily quotas, so a bug or abuse can't run up a bill. Console → APIs & Services → each API → Quotas:
  - Routes API (Compute Routes): requests per day, e.g. 2,000
  - Air Quality API (current conditions + forecast): requests per day, e.g. 40,000 (each route request uses ~15–60)
  - Places API (New) Autocomplete: requests per day, e.g. 5,000
  - When a quota is hit, the app falls back to open data automatically instead of failing.
- [x] Spending cap built in: `GOOGLE_DAILY_BUDGET_USD` (default 10 USD/day). Past it, searches use free open data until midnight IST. Raise it with `gcloud run services update breatheasy --region=asia-south1 --update-env-vars=GOOGLE_DAILY_BUDGET_USD=25`.
- [x] India prices (Nov 2026) are the defaults in `backend/app/config.py` (`PRICE_*`), so each response carries its estimated Google cost. Re-check the price list every few months.
- [ ] Artifact Registry cleanup, so old images don't pile up (each deploy adds one, about 250 MB): `gcloud artifacts repositories set-cleanup-policies breatheasy --location=asia-south1 --policy=<(echo '[{"name":"keep-10","action":{"type":"Keep"},"mostRecentVersions":{"keepCount":10}},{"name":"delete-old","action":{"type":"Delete"},"condition":{"olderThan":"30d"}}]')`

## 2. Google sign-in

- [ ] **(blocking)** OAuth consent screen (Console → Google Auth Platform → Branding): app name, support email, logo (`frontend/public/icons/icon-512.png`), **privacy policy URL `https://YOUR-URL/privacy`**, **terms URL `https://YOUR-URL/terms`**, authorised domain.
- [ ] **(blocking)** OAuth client (Web application): add the Cloud Run URL (and custom domain) to *Authorized JavaScript origins*. Put the Client ID in `deploy/cloudrun/deploy.env` → `OAUTH_CLIENT_ID`, redeploy.
- [ ] Audience: while "Testing", only listed test users can sign in. Click **Publish app** when ready. Basic scopes (email, profile, openid) don't need Google verification.

## 3. Legal and content

- [x] Operator and contact on the privacy policy and terms come from config (`OPERATOR_NAME`, default "Dr Amith Paruchuri"; `CONTACT_EMAIL`, default: the email in `USER_AGENT`).
- [ ] **(blocking)** Re-read both pages against how you actually run the service (region, retention, providers). Have them reviewed; the app collects location history for signed-in users, which is personal data under India's DPDP Act 2023.
- [ ] Decide whether to name a grievance officer (required for some entities under Indian IT rules; check what applies to you).
- [ ] Google Maps Platform terms: Google route data is only ever shown on a Google map (enforced: production refuses to start without a browser key). Attribution is drawn by the Maps SDK.

## 4. First deploy

- [ ] `./deploy/cloudrun/deploy.sh`. It prints the URL and checks `/readyz`.
- [ ] Open the URL on desktop and phone:
  - [ ] Map loads (if blank: browser key referrer restriction or Maps JavaScript API not enabled).
  - [ ] Place search, route planning in all four modes.
  - [ ] Sign in, save Home and Work, press Navigate, see the trip in Account.
  - [ ] "Add to Home screen" works on Android Chrome and iPhone Safari.
- [ ] Open DevTools console and look for `Content-Security-Policy` report-only warnings while using maps and sign-in. If there are none, set `CSP_MODE=enforce` in `deploy.env` and redeploy. If something is blocked, add the domain in `backend/app/web.py:content_security_policy()`.
- [ ] Look at logs: `gcloud run services logs read breatheasy --region=asia-south1`. There should be no `ERROR` lines and no fallback warnings when Google is healthy.

## 5. Shareable link and custom domain

- [ ] Short link on Vercel (free, two minutes): Vercel → Add New → Project → import `Amith-paruchuri/breatheasy` → **Root Directory `deploy/vercel`**, preset **Other** → Deploy. Visitors to `breatheasy.vercel.app` (or whatever name Vercel gives) are redirected to the app. Vercel's free Hobby plan is for non-commercial use, so move to a custom domain before charging money.
- [ ] Custom domain (for a commercial launch): buy e.g. `breatheasy.in`, then put Firebase Hosting (same Google project, free tier) in front of the Cloud Run service with a rewrite of `**` to `breatheasy`, or use Cloud Run's custom domain mapping if your region offers it.
- [ ] Add the domain to the OAuth client origins, and set `CUSTOM_DOMAIN=yourdomain` in `deploy.env` so the browser key allows it; redeploy.

## 6. Operations

- [ ] Uptime check: Cloud Monitoring → Uptime checks → HTTPS `https://YOUR-URL/readyz` every 5 min, alert by email.
- [ ] Error alert: Logging → create a log-based alert on `severity>=ERROR` for the service.
- [ ] Backups: Cloud SQL daily backups (7 kept) are on. Test a restore once into a scratch instance.
- [x] Releases: every push to `main` on GitHub runs `cloudbuild.yaml` (tests, image, deploy) through the `breatheasy-main` Cloud Build trigger, and GitHub Actions CI. Roll back in Cloud Run → Revisions → route 100% to the previous revision.
- [ ] Daily spend: the `api_spend` table in Cloud SQL has one row per day (searches, calls, estimated USD). Cloud SQL Studio → `SELECT * FROM api_spend ORDER BY day DESC;`
- [ ] Rotating secrets: `gcloud secrets versions add breatheasy-session-secret --data-file=-` (signs everyone out) or a new server key, then redeploy.

## 7. Before calling it "validated"

- [ ] Run `backend/scripts/compare_routes.py` on Google data at morning and evening peaks: how often is there a ≥10% cleaner route within 10 minutes?
- [ ] Do a few sensor walks with `validate_with_sensor.py` before making health claims in marketing.
