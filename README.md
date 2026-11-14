<p align="center">
  <img src="docs/assets/hero.svg" alt="Breatheasy: the cleanest route, not just the fastest one" width="100%">
</p>

<p align="center">
  <a href="https://breatheasy-2lqwczvwyq-el.a.run.app"><img alt="Live app" src="https://img.shields.io/badge/live_app-open-3FD39A?style=for-the-badge"></a>
  <a href="https://youtu.be/cBiJ1rxy1WY"><img alt="Demo video" src="https://img.shields.io/badge/demo-2_min_video-E5484D?style=for-the-badge"></a>
  <a href="https://breatheasy-2lqwczvwyq-el.a.run.app/validation"><img alt="Validation" src="https://img.shields.io/badge/validation-live-7FB7FF?style=for-the-badge"></a>
  <a href="LICENSE"><img alt="MIT licence" src="https://img.shields.io/badge/licence-MIT-9FB0AA?style=for-the-badge"></a>
</p>

<p align="center"><b>Every navigation app shows you the fastest route. Breatheasy shows you the cleanest one.</b><br>
Built by Dr Amith Paruchuri, final-year medical student at AIIMS New Delhi, for <i>Code for a Billion</i> (Climate track).</p>

---

## The problem

<img src="docs/assets/problem.svg" alt="India is the 6th most polluted country; Delhi's PM2.5 is 20 times the WHO limit; Loni in Delhi-NCR is the most polluted city on Earth; 1.67 million deaths in India from air pollution in 2019" width="100%">

Hundreds of millions of Indians breathe this air on the road every day: commuters, delivery riders, children on the school run. Pollution is not the same on every street: a busy main road carries far more exhaust than a lane beside a park. Yet every navigation app picks only the fastest route, and nobody can see which way is cleaner.

## The cleanest route, not the fastest

<img src="docs/assets/fastest-vs-cleanest.svg" alt="Animated illustration: maps pick the direct busy main road past construction and a factory; Breatheasy picks the cleanest road through a park and past a lake" width="100%">

| | Navigation apps | AQI apps | **Breatheasy** |
|---|:---:|:---:|:---:|
| **Cleanest route for your trip** | ✗ fastest only | ✗ | **✓** |
| Pollution spots marked on your route | ✗ | ✗ | **✓** |
| Stricter mode for asthma, pregnancy, children | ✗ | ✗ | **✓** |
| Turn-by-turn navigation | ✓ | ✗ | **✓ via Google Maps, same streets** |
| Checks itself against monitoring stations, in public | ✗ | ✗ | **✓** |
| *Bonus:* best time to leave, for that exact route | ✗ | general forecast | **✓** |

## The app

<img src="docs/assets/screens.png" alt="Breatheasy screens: routes coloured by PM2.5 with pollution spots, a route card with PM2.5, AQI and minutes in bad air, and the I'm sensitive setting" width="100%">

- **Cleanest route:** routes ranked by the PM2.5 you actually pass through, not by speed. Each shows its average PM2.5 and AQI and the minutes you would spend in very poor air.
- **Pollution spots:** red markers on the dirtiest stretches, so you can see why one road is worse.
- **I'm sensitive:** keeps people with asthma, pregnant women, children and older adults further from busy roads.
- **Go:** one tap hands the exact route to Google Maps; Share sends it on WhatsApp. Works anywhere in India, installable on any phone.
- **Extras:** a commute agent (*"reach Hauz Khas by 9 am on my cycle"*), and a *best time to leave* hint for the same route.

## How it works

<img src="docs/assets/how-it-works.svg" alt="Six steps: your trip, candidate routes, air on each route, rank, best time, go in Google Maps" width="100%">

Air comes from Google's Air Quality model (500 m grid, hourly forecast), adjusted street by street with OpenStreetMap: up beside busy main roads, down beside parks and lakes (Delhi-NCR, Mumbai, Kolkata, Bengaluru, Hyderabad).

## Validation and real-world impact

<img src="docs/assets/validation.svg" alt="85% right order against monitoring stations, correlation 0.87, 100% Google Maps match, a cleaner route on 74% of Delhi trips" width="100%">

| Check | What we measure | Result so far |
|---|---|---|
| **Monitoring stations** (every 3 hours) | Our estimate vs official station readings, same spot and hour | **85%** right order on 1,417 station pairs · r = **0.87** · 220 comparisons at 165 stations |
| **Cleanest route vs fastest** (127 trips, 5 cities) | Is there a route with cleaner air than the fastest one? | yes on **74%** of Delhi trips, typically ~3% cleaner for ~10 min |
| **Real commutes** | Does Google Maps follow the cleanest route we hand it? | **100%** median match, phone and computer |
| *Bonus:* best time to leave | Same route, leaving now vs up to 2 hours later | up to **26%** cleaner; median **17%** in Mumbai |
| **People using it** | Searches, trips started on a cleaner route, departures moved to a cleaner time, "would you take it again?" | live, anonymous: [/stats](https://breatheasy-2lqwczvwyq-el.a.run.app/stats) |

**See it yourself:** [live validation page](https://breatheasy-2lqwczvwyq-el.a.run.app/validation) · [raw numbers](https://breatheasy-2lqwczvwyq-el.a.run.app/api/validation/summary) · [method and limits](VALIDATION.md)

We report the numbers as they are, including the modest ones: smog spreads across a whole city, so the cleanest route avoids part of it, not all of it. Every limit is listed in [VALIDATION.md](VALIDATION.md).

## Built in AgentFoundry

The project lives in the AgentFoundry IDE. The commute agent ([`backend/app/agent.py`](backend/app/agent.py), with [tests](backend/tests/test_agent.py)) was built there with the Gemini CLI: the plain-language parser, the departure-time search and its tests.

## Run it

```bash
./start.sh            # macOS / Linux  (Windows: start.bat), then open http://localhost:5173
cd backend && pytest  # 109 tests
```

Runs on free open data locally, no keys needed. Production setup, architecture, costs and ranking details: [docs/TECHNICAL.md](docs/TECHNICAL.md).

**Stack:** React + TypeScript PWA · FastAPI · Postgres · Google Routes, Air Quality, Places · OpenStreetMap · Google Cloud Run (Mumbai), auto-deployed from this repo.

## Next

Paired walks with a portable PM2.5 sensor on recommended vs fastest routes · a pilot with AIIMS colleagues and patients with asthma · Hindi and other Indian languages · morning alerts for saved commutes.

<sub>MIT licence. Map data © OpenStreetMap contributors. Air data: Google Air Quality API; station readings via OpenAQ (CPCB network). Pollution facts: IQAir World Air Quality Report 2025; Lancet Planetary Health 2021.</sub>
