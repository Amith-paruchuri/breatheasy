# Breatheasy

**Cleaner-air routes for Delhi-NCR.** Air pollution isn't the same on every street: a busy arterial road can carry far more fine dust than a lane beside a park a few hundred metres away, but navigation apps only optimise for time. Breatheasy compares up to eight candidate routes for a trip (Google's own, side streets, and routes through nearby parks and lakes), estimates the PM2.5 and AQI along each one, and recommends the cleanest within the extra time you accept. It works for walking, cycling, two-wheelers and cars, explains why a route is cleaner ("Passes Lodhi Garden, about 8 min beside greenery"), and hands the exact route to Google Maps for navigation.

**Live app:** https://breatheasy-2lqwczvwyq-el.a.run.app (installable on phones as an app)

**Stack:** React + TypeScript (Vite, installable PWA) · FastAPI · SQLAlchemy + Alembic · Postgres (Cloud SQL) · Google Routes, Air Quality, Places, Maps JS and Identity · OpenStreetMap street context · one container on Google Cloud Run, deployed automatically from this repo by Cloud Build.

**Licence:** MIT (see [LICENSE](LICENSE)). Map data © OpenStreetMap contributors (ODbL).

## Go live on Google Cloud

You need a Google Cloud project with billing on. Everything else is scripted; open [Cloud Shell](https://shell.cloud.google.com) (gcloud is already signed in there), upload or clone this folder, then:

```bash
./deploy/cloudrun/setup.sh    # once: APIs, database, API keys, secrets, sign-in client
./deploy/cloudrun/deploy.sh   # first release: build, deploy, lock the browser key to your URL
```

After that, every push to `main` deploys automatically through the `cloudbuild.yaml` Cloud Build trigger (tests, image, rollout).

`setup.sh` creates restricted API keys itself and stores secrets in Secret Manager, so **API keys never need to be pasted into chat, code or config files**. If you already have keys, it asks for them with hidden input instead. One step is manual: creating the OAuth client for Google sign-in (the script prints the exact console links).

Then go through [`deploy/LAUNCH_CHECKLIST.md`](deploy/LAUNCH_CHECKLIST.md): budget alert, API quotas, consent screen, privacy policy details, CSP switch-over, monitoring.

### What production runs

| | |
|---|---|
| Hosting | Cloud Run, `asia-south1` (Mumbai), scales 0 → 4 instances, HTTPS |
| Database | Cloud SQL Postgres 16, smallest tier, daily backups kept 7 days; migrations run automatically on deploy (advisory-locked, safe with several instances) |
| Secrets | Secret Manager: database URL, session secret, Maps server key |
| Data | Google Routes + Air Quality + Places; automatic fallback to open data if Google errors or a quota runs out, with a notice in the app |
| Accounts | Google sign-in; HttpOnly, Secure, SameSite cookie sessions; "sign out everywhere"; export and delete-account built in |
| Safety | Startup refuses unsafe production config; CSRF header check; security headers + CSP; per-IP rate limits; logs never contain search text or coordinates; trips auto-deleted after 12 months |

Approximate fixed cost: Cloud SQL smallest tier is the main one (roughly ₹700–1,000/month); Cloud Run is near zero at low traffic. Google Maps usage is pay-per-call beyond the monthly free usage: set the quotas in the checklist.

## Run it on your computer

Needs Python 3.10+ and Node.js 18+.

- **macOS / Linux:** `./start.sh` · **Windows:** double-click `start.bat`
- Open http://localhost:5173

Locally it defaults to **open data** (no keys): OpenStreetMap routing, Open-Meteo air quality (coarse ~40 km grid, so nearby routes usually look alike), Photon search, OSM map. Sign-in is off until you set `GOOGLE_OAUTH_CLIENT_ID` in `backend/.env` (add `http://localhost:5173` to the OAuth client's origins). `PROVIDER=mock` gives synthetic data offline.

Production-like local run with Postgres: `cp backend/.env.example .env.compose && docker compose up --build` → http://localhost:8080

Tests: `cd backend && pip install -r requirements-dev.txt && pytest` (87 tests; set `TEST_DATABASE_URL` to also run them on Postgres). CI runs both plus the frontend build and the Docker image on every push.

## How Breatheasy ranks routes

- **Cleanest air (default):** the route with the lowest average AQI on India's CPCB scale, allowing up to 45 extra minutes by default (or "any extra time"). Built for people who will take a longer, cleaner way: runners, walkers, unhurried trips. If a much longer route means more total exposure, the card says so.
- **Balanced:** a longer route only when it clearly cuts the total pollution you breathe.
- **Fastest:** the quickest route, with its air shown.

AQI is computed from all pollutants the data source gives (PM2.5, PM10, NO2, O3, CO, SO2) using the CPCB breakpoints, applied to hourly model values (the official index uses 24-hour averages, so treat it as an estimate).

**Street-level context** comes from OpenStreetMap: parks, forests, lakes, busy main roads, industrial areas and mapped construction sites. It is used to (1) describe each route ("Passes Lodhi Garden, about 8 min beside greenery"), (2) nudge modelled pollution up beside busy roads (+15%) and slightly down beside green space (−5%), both configurable, and (3) find extra candidate routes that pass large parks and lakes near the trip. `deploy.sh` builds this layer from OpenStreetMap the first time it runs (`backend/scripts/build_environment.py`; delete `backend/app/data/environment.json.gz` to refresh). Map data © OpenStreetMap contributors, ODbL.

## How a request works

```
origin, destination, mode, preference, time budget
        │
        ▼
1. Candidates   Routes API: primary + alternatives  ──┐
                + 2 "via" detours offset to each side │  near-duplicates dropped
                of the fastest route's midpoint     ──┘  (≥85% shared geometry)
        │
2. Segments     each route cut into ~400 m pieces; time per piece from the
                engine's step durations, rescaled to the traffic-aware total
        │
3. Air quality  each piece snapped to a ~500 m cell (matches Google's grid);
                one lookup per cell shared across ALL routes;
                pieces reached this hour → current conditions,
                later pieces → hourly forecast for the hour you'll be there
        │
4. Exposure     E = Σ PM2.5ᵢ × minutesᵢ   (µg/m³·min, relative indicator)
        │
5. Ranking      fastest | cleanest within budget |
                balanced: reduction% − 1.5 × extra minutes
                If the best gain is < 10%, recommend the fastest route and say why.
```

Code map:

| Path | What it does |
|---|---|
| `backend/app/providers/google.py` | Routes API, Air Quality API (current + forecast), Places API (New) |
| `backend/app/providers/open.py` | Keyless OSRM routing, Open-Meteo air quality (batched), Photon search |
| `backend/app/providers/mock.py` | Synthetic routes and pollution field for offline work |
| `backend/app/services/candidates.py` | Alternatives, waypoint detours, de-duplication |
| `backend/app/services/sampling.py` | Timed segments along a route |
| `backend/app/services/airquality.py` | Cell de-duplication, current vs forecast, cache |
| `backend/app/services/exposure.py` | Exposure model and coverage |
| `backend/app/services/ranking.py` | Preferences, budget, meaningful-difference rule |
| `backend/app/services/planner.py` | Orchestration, hotspots, optional research log |
| `backend/app/providers/fallback.py` | Google first, open data on quota/key/outage errors, with a circuit breaker |
| `backend/app/auth.py`, `routers/account.py` | Google sign-in, session cookies, saved places, trip log, export, deletion |
| `backend/app/db.py`, `migrations/` | SQLAlchemy models and Alembic migrations (SQLite dev, Postgres prod) |
| `backend/app/web.py` | Security headers, CSRF guard, JSON logs, rate limits, serving the built app |
| `frontend/src/` | React app: search, modes, preferences, route cards, colour-coded map, account, legal pages |
| `frontend/public/sw.js`, `manifest.webmanifest` | Installable app and offline shell |
| `deploy/cloudrun/` | `setup.sh` (one-time GCP setup) and `deploy.sh` (build + release) |

All tunables (sample spacing, detours, threshold, balanced trade-off, cache TTLs, rate limit) are in `backend/.env.example`.

## Research scripts (the "Key questions" in the proposal)

**Batch feasibility study** (Q1, Q2, Q3, Q5):

```bash
cd backend
python -m scripts.compare_routes scripts/od_pairs_delhi.csv --modes WALK TWO_WHEELER --budget 10 --out results.csv
python -m scripts.compare_routes scripts/od_pairs_delhi.csv --no-detours --out results_nodetour.csv
```

Per trip it records the best in-budget reduction vs fastest, whether that route came from a detour, distinct grid cells, API calls and cost. Run it at several departure times (`--depart 2026-10-23T08:30`) and with and without detours to see whether detours earn their extra calls.

**Field validation with a portable sensor** (Challenge 6): plan a trip, open *Request details* under the results and press *Download trip data*, travel the route with a GPS-logging PM2.5 monitor exported as `timestamp,lat,lng,pm25`, then:

```bash
python -m scripts.validate_with_sensor trip.json sensor.csv --route r2
```

It reports predicted vs measured exposure and the segment-level Spearman correlation. Calibrate low-cost sensors against a reference monitor before trusting absolute values.

`LOG_JOURNEYS=true` writes one line per request (coordinates rounded to ~110 m) to `data/journeys.jsonl` for usage analysis. Off by default; tell pilot users if you turn it on.

## Cost

With default settings a typical Delhi trip costs about **3 Routes calls + 15 to 60 Air Quality calls**. Most of the AQ cost comes from the number of distinct 500 m cells, and from forecast lookups for walks longer than an hour. Levers, in order of impact:

- `DETOUR_COUNT=0` drops two Routes calls and the cells only the detours touch.
- `SAMPLE_SPACING_M=500` or larger; finer sampling than the data's 500 m grid adds calls, not information.
- Re-ranking the same trip (changing preference or budget) is served from a 2-minute candidate cache and costs nothing.
- The AQ cache (`AQ_CACHE_TTL_S`) lets nearby trips share cells.

**Check the Google Maps Platform terms for caching.** Both caches are short, in-memory and configurable; set the TTLs to what the current service-specific terms allow (or 0).

## Known limits (worth stating in any pitch)

- Google's AQ data is modelled on a ~500 m grid. Two routes a few streets apart often fall in the same cells, so many trips will show no meaningful difference. The app says so instead of inventing one; the batch script measures how often that happens.
- Exposure is concentration × time, not inhaled dose. It ignores breathing rate (a cyclist breathes more than a car passenger), vehicle ventilation and road-edge effects. Compare routes within one mode only.
- Bicycle routing coverage in India is limited; the app reports when no route exists for a mode.
- Google's terms require Google route data to be shown on a Google map. The schematic view is for demo mode only.
- Turn-by-turn navigation is handed to Google Maps with three intermediate waypoints so it follows the same corridor; Google Maps may still re-route.

## Roadmap from here

- **Phase 2:** compare detour strategies (more offsets, 1/3 and 2/3 anchors via `DETOUR_COUNT=4`) using the batch script.
- **Phase 3:** add CPCB station data as a second provider (implement `AirQualityProvider` in `providers/`), blend with traffic as a predictor, and report uncertainty bands per route.
- **Phase 4:** OSRM/GraphHopper with pollution-weighted edge costs (PostGIS) once segment-level estimates prove worth it.
- Mode-specific ventilation factors if you want a dose proxy rather than a concentration-time proxy.

## Releases and rollback

`deploy.sh` tags each image with the git commit. To roll back: Cloud Run → service → Revisions → send 100% traffic to the previous revision. Database migrations only add things in this version; write a new migration (`alembic revision`) for any schema change, never edit tables by hand.
