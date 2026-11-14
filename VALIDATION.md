# How we check that Breatheasy works

Everything below runs on the live app and is published as it comes in, with nothing filtered out.

- Live results page: https://breatheasy-2lqwczvwyq-el.a.run.app/validation
- Raw numbers (JSON): https://breatheasy-2lqwczvwyq-el.a.run.app/api/validation/summary
- Usage and behaviour counts: https://breatheasy-2lqwczvwyq-el.a.run.app/stats (JSON: `/api/stats`)

The figures in this file are snapshots; the links above are always current.

## 1. Accuracy against official monitoring stations

**Question.** Does Breatheasy's air estimate match what India's monitoring stations measure, and, most important for routing, does it put places in the right order (which one is dirtier)?

**Method.** Every three hours a scheduled job (`POST /api/validation/run`, Cloud Scheduler) takes the latest hourly PM2.5 readings from stations in India (CPCB network, read through OpenAQ; data.gov.in as a fallback), samples about 60 of them (60% in Delhi-NCR, Mumbai, Kolkata, Bengaluru and Hyderabad), and asks Google's Air Quality model for the same spot and the same hour. We store both values, plus the value after Breatheasy's street adjustment (up beside busy main roads, down beside parks and lakes). Code: `backend/app/validation.py`; tests: `backend/tests/test_validation.py`.

**Measures.**
- *Right order*: for every pair of stations in the same city and run whose readings differ by at least 10 µg/m³, does the estimate say the same one is dirtier? This is what route choice depends on.
- *Correlation* (Pearson r), *typical error* (median absolute error), *bias* (average of estimate minus station), share within 25%.
- *Street adjustment*: error at stations beside busy roads and beside parks, with and without the adjustment.

**Snapshot (14 Nov 2026, evening, after 9 runs):** 426 comparisons at 260 stations.

| Measure | All cities | Delhi |
|---|---|---|
| Right order | 81% of 2,839 pairs | 78% of 1,681 pairs |
| Correlation | 0.82 | |
| Typical error | ±15 µg/m³ | |
| Bias | about 6 µg/m³ lower than stations | |

A consistent offset does not change which route is cleaner, which is why ordering is the headline measure.

**Street adjustment:** beside parks and lakes (32 stations) the adjustment cut the typical error from ±10 to ±8 µg/m³. Beside busy roads (11 stations) it overshot, raising the error from ±9 to ±15 µg/m³, so the busy-road correction is too strong and will be retuned. We report both.

## 2. Trip benchmark: real commutes in five cities

**Question.** On realistic trips, how often is there a cleaner route than the fastest one, how much cleaner, at what cost in time; and does Google Maps then follow the route we hand it?

**Method.** `POST /api/validation/benchmark` plans trips between well-known places (metro stations, hospitals, colleges, markets) in Delhi-NCR, Mumbai, Kolkata, Bengaluru and Hyderabad, on foot, by cycle and by two-wheeler, with distances suited to each mode. For each trip it records the fastest and the recommended route (average PM2.5, minutes in poor air, minutes beside busy roads and parks). It then sends the recommended route to Google's Routes API with exactly the pins that the app's "Start in Google Maps" link uses (3 on phones, up to 8 on computers) and measures how much of Google's path lies within 40 m of ours. Code: `backend/app/benchmark.py`; tests: `backend/tests/test_benchmark.py`.

**Results so far (127 trips):**
- **Google Maps follows our route: median 100%** of Google's path within 40 m of Breatheasy's, on phones and on computers.
- **Cleaner routes:** in Delhi-NCR a cleaner route than the fastest existed on 74% of trips, typically about 9 µg/m³ (3%) cleaner for about 10 extra minutes. In the other four cities the fastest route was usually also the cleanest at our threshold.

We state the modest route gains plainly: smog spreads across a whole city, so any one route can only avoid part of it. That is why timing is measured too.

## 3. Best time to leave

**Question.** Does leaving a little later give cleaner air on the same route?

**Method.** For each benchmark trip, the recommended route is scored leaving now and in 30, 60, 90 and 120 minutes, from Google's hourly forecast along the route (`backend/app/besttime.py`, `POST /api/best-time`).

**Results so far:** waiting up to two hours gave at least 10% cleaner air on 12.8% of trips, and up to 26%. It varies by city and hour: in Mumbai the median gain from leaving at the best time was 17%; in Delhi's evening smog it was usually best to leave now.

## 4. What people do with it (behaviour, not just visits)

The app counts, anonymously (event, day and city area only; no accounts, locations or IP addresses), at `/stats`:
- route searches and commute-agent questions
- trips started in Google Maps, and **trips started on a route other than the fastest**
- **departures moved to a cleaner time** (a later slot picked in Best time to leave)
- shares, and shared links opened
- a one-tap question after a trip handed to Google Maps: **"Would you take that route again?"** (yes/no)

## 5. Software checks

109 automated tests (`cd backend && python -m pytest -q`) run on every push; a failing test blocks the deploy (`cloudbuild.yaml`).

## Limits

- Stations are fixed points, often on rooftops; a route is a moving line at street level. Agreement at stations is necessary, not proof for every street.
- Google's model works on a grid of about 500 m; differences between nearby streets come partly from the street adjustment, which is still being checked (section 1).
- OpenAQ carries official CPCB stations and some other monitors; data.gov.in, the official source, does not answer requests from Google Cloud, so it is only a fallback.
- No field measurements yet. Next: paired walks with a portable PM2.5 sensor along recommended and fastest routes, and a pilot with AIIMS colleagues and patients with asthma.
