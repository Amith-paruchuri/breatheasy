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
- [ ] Check the Maps Platform monthly free usage and current prices for each SKU, and copy prices into `PRICE_*` settings if you want cost-per-journey in responses.

## 2. Google sign-in

- [ ] **(blocking)** OAuth consent screen (Console → Google Auth Platform → Branding): app name, support email, logo (`frontend/public/icons/icon-512.png`), **privacy policy URL `https://YOUR-URL/privacy`**, **terms URL `https://YOUR-URL/terms`**, authorised domain.
- [ ] **(blocking)** OAuth client (Web application): add the Cloud Run URL (and custom domain) to *Authorized JavaScript origins*. Put the Client ID in `deploy/cloudrun/deploy.env` → `OAUTH_CLIENT_ID`, redeploy.
- [ ] Audience: while "Testing", only listed test users can sign in. Click **Publish app** when ready. Basic scopes (email, profile, openid) don't need Google verification.

## 3. Legal and content

- [ ] **(blocking)** In `frontend/src/pages/Legal.tsx` set `OPERATOR` and `CONTACT`, and re-read both pages against how you actually run the service (region, retention, providers). Have them reviewed; the app collects location history for signed-in users, which is personal data under India's DPDP Act 2023.
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

## 5. Custom domain (optional)

- [ ] Cloud Run → Manage custom domains (or a load balancer) → map `breatheasy.in` or similar; DNS records as shown.
- [ ] Add the domain to the OAuth client origins, and set `CUSTOM_DOMAIN=yourdomain` in `deploy.env` so the browser key allows it; redeploy.

## 6. Operations

- [ ] Uptime check: Cloud Monitoring → Uptime checks → HTTPS `https://YOUR-URL/readyz` every 5 min, alert by email.
- [ ] Error alert: Logging → create a log-based alert on `severity>=ERROR` for the service.
- [ ] Backups: Cloud SQL daily backups (7 kept) are on. Test a restore once into a scratch instance.
- [ ] Releases: `git push` runs CI (tests on SQLite + Postgres, build, image). Deploy with `deploy.sh`; roll back in Cloud Run → Revisions → route 100% to the previous revision.
- [ ] Rotating secrets: `gcloud secrets versions add breatheasy-session-secret --data-file=-` (signs everyone out) or a new server key, then redeploy.

## 7. Before calling it "validated"

- [ ] Run `backend/scripts/compare_routes.py` on Google data at morning and evening peaks: how often is there a ≥10% cleaner route within 10 minutes?
- [ ] Do a few sensor walks with `validate_with_sensor.py` before making health claims in marketing.
