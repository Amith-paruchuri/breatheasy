"""Trip benchmark: what Breatheasy changes on real commutes, and whether Google Maps
then follows the chosen route.

POST /api/validation/benchmark (scheduler token) runs Breatheasy on realistic trips
between well-known places (metro stations, hospitals, colleges, markets) in the five
street-layer cities, by walking, cycling and two-wheeler, and stores per trip:

- how much cleaner the recommended route is than the fastest one (average PM2.5),
  how many extra minutes it costs, and minutes in poor air on each
- hand-off fidelity: the recommended route is sent to Google's Routes API with the
  same pins the app puts in the Google Maps link (3 for phones, up to 8 for computers),
  and we measure how much of Google's path lies on our route (within 40 m)

The summary is published at /api/validation/summary under "benchmark".
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import statistics
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Header, HTTPException, Request

from .models import LatLng, Preference, RouteRequest, TravelMode, Usage
from .services.planner import plan_routes
from .validation import metadata

log = logging.getLogger("breatheasy.benchmark")
router = APIRouter()

trips = sa.Table(
    "benchmark_trips",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("run_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("city", sa.String(40), nullable=False),
    sa.Column("mode", sa.String(16), nullable=False),
    sa.Column("origin", sa.String(80), nullable=False),
    sa.Column("destination", sa.String(80), nullable=False),
    sa.Column("routes", sa.Integer, nullable=False),
    sa.Column("fastest_min", sa.Float, nullable=False),
    sa.Column("chosen_min", sa.Float, nullable=False),
    sa.Column("fastest_pm25", sa.Float),
    sa.Column("chosen_pm25", sa.Float),
    sa.Column("fastest_bad_min", sa.Float),
    sa.Column("chosen_bad_min", sa.Float),
    sa.Column("bad_level", sa.Integer),
    sa.Column("chosen_green_min", sa.Float),
    sa.Column("fastest_green_min", sa.Float),
    sa.Column("chosen_road_min", sa.Float),
    sa.Column("fastest_road_min", sa.Float),
    sa.Column("differs", sa.Boolean, nullable=False),  # recommended route is not the fastest
    sa.Column("fidelity3", sa.Float),  # share of Google's path on our route, 3 pins (phone)
    sa.Column("fidelity8", sa.Float),  # same with up to 8 pins (computer)
)

# Well-known places: (name, lat, lng). Coordinates are approximate; routing snaps to roads.
PLACES = {
    "Delhi-NCR": [
        ("AIIMS", 28.5672, 77.2100), ("Connaught Place", 28.6315, 77.2167), ("Hauz Khas", 28.5494, 77.2001),
        ("Lajpat Nagar", 28.5677, 77.2433), ("Karol Bagh", 28.6519, 77.1909), ("Saket", 28.5245, 77.2066),
        ("Nehru Place", 28.5491, 77.2533), ("Rajiv Chowk", 28.6328, 77.2197), ("Khan Market", 28.6003, 77.2270),
        ("Green Park", 28.5590, 77.2066), ("India Gate", 28.6129, 77.2295), ("Kashmere Gate", 28.6675, 77.2280),
        ("Dwarka Sec 21", 28.5523, 77.0583), ("Noida Sec 18", 28.5705, 77.3218), ("Cyber City", 28.4950, 77.0890),
    ],
    "Mumbai": [
        ("CST", 18.9398, 72.8355), ("Churchgate", 18.9322, 72.8264), ("Dadar", 19.0178, 72.8478),
        ("Bandra", 19.0544, 72.8406), ("Andheri", 19.1197, 72.8464), ("Powai", 19.1176, 72.9060),
        ("Worli", 19.0176, 72.8162), ("Lower Parel", 18.9953, 72.8300), ("BKC", 19.0660, 72.8677),
        ("KEM Hospital", 19.0026, 72.8420), ("Kurla", 19.0726, 72.8845), ("Juhu", 19.1075, 72.8263),
    ],
    "Kolkata": [
        ("Esplanade", 22.5646, 88.3524), ("Park Street", 22.5530, 88.3520), ("Howrah", 22.5839, 88.3426),
        ("Salt Lake Sec V", 22.5726, 88.4335), ("Gariahat", 22.5180, 88.3655), ("SSKM Hospital", 22.5390, 88.3440),
        ("College Street", 22.5755, 88.3630), ("Ballygunge", 22.5280, 88.3650), ("New Market", 22.5600, 88.3510),
        ("Dum Dum", 22.6230, 88.4180), ("Tollygunge", 22.4980, 88.3460),
    ],
    "Bengaluru": [
        ("MG Road", 12.9756, 77.6066), ("Majestic", 12.9767, 77.5713), ("Koramangala", 12.9352, 77.6245),
        ("Indiranagar", 12.9784, 77.6408), ("Jayanagar", 12.9308, 77.5838), ("Malleshwaram", 13.0035, 77.5647),
        ("Whitefield", 12.9698, 77.7500), ("HSR Layout", 12.9116, 77.6474), ("Electronic City", 12.8452, 77.6602),
        ("Hebbal", 13.0358, 77.5970), ("NIMHANS", 12.9416, 77.5960), ("Lalbagh", 12.9507, 77.5848),
    ],
    "Hyderabad": [
        ("Charminar", 17.3616, 78.4747), ("HITEC City", 17.4435, 78.3772), ("Banjara Hills", 17.4138, 78.4398),
        ("Secunderabad", 17.4399, 78.4983), ("Ameerpet", 17.4375, 78.4482), ("Gachibowli", 17.4401, 78.3489),
        ("Kukatpally", 17.4849, 78.4138), ("Begumpet", 17.4440, 78.4630), ("Osmania Hospital", 17.3713, 78.4756),
        ("Jubilee Hills", 17.4326, 78.4071), ("Abids", 17.3930, 78.4760),
    ],
}
MODES = [TravelMode.WALK, TravelMode.BICYCLE, TravelMode.TWO_WHEELER]
TRIP_KM = {TravelMode.WALK: (1.2, 4.5), TravelMode.BICYCLE: (2.5, 9), TravelMode.TWO_WHEELER: (4, 15)}
DEVIATE_M = {"WALK": 40, "BICYCLE": 60, "TWO_WHEELER": 90, "DRIVE": 90}


def _dist_m(a, b) -> float:
    k = 111320.0
    dx = (a[1] - b[1]) * k * math.cos(math.radians((a[0] + b[0]) / 2))
    dy = (a[0] - b[0]) * k
    return math.hypot(dx, dy)


def _dist_to_line(p, line) -> float:
    best = float("inf")
    k = 111320.0
    c = math.cos(math.radians(p[0]))
    px, py = p[1] * k * c, p[0] * k
    for a, b in zip(line, line[1:]):
        ax, ay, bx, by = a[1] * k * c, a[0] * k, b[1] * k * c, b[0] * k
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
        best = min(best, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return best


def waypoints(path, base, mode: str, max_pins: int) -> list[tuple[float, float]]:
    """Same rule as the app's Google Maps link (frontend/src/format.ts routeWaypoints)."""
    if len(path) < 3 or max_pins < 1:
        return []
    cum = [0.0]
    for i in range(1, len(path)):
        cum.append(cum[-1] + _dist_m(path[i - 1], path[i]))
    total = cum[-1]
    if total < 800:
        return []
    n = max(1, min(max_pins, round(total / 1500)))
    edge = min(250, total * 0.05)
    thr = DEVIATE_M.get(mode, 90)
    out = []
    for k in range(n):
        lo, hi = max(edge, total * k / n), min(total - edge, total * (k + 1) / n)
        mid = (lo + hi) / 2
        pick, best_dev, mid_idx, best_mid = -1, thr, -1, float("inf")
        for i in range(1, len(path) - 1):
            if cum[i] < lo or cum[i] > hi:
                continue
            if len(base) > 1:
                d = _dist_to_line(path[i], base)
                if d > best_dev:
                    best_dev, pick = d, i
            m = abs(cum[i] - mid)
            if m < best_mid:
                best_mid, mid_idx = m, i
        idx = pick if pick >= 0 else mid_idx
        if idx >= 0:
            out.append(path[idx])
    return out


def overlap(google_path, ours, tol_m=40.0) -> float | None:
    """Share of Google's path (by length) lying within tol_m of our route."""
    if len(google_path) < 2 or len(ours) < 2:
        return None
    on = tot = 0.0
    for a, b in zip(google_path, google_path[1:]):
        seg = _dist_m(a, b)
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        tot += seg
        if _dist_to_line(mid, ours) <= tol_m:
            on += seg
    return on / tot if tot else None


def pick_trips(n: int, seed: int | None = None) -> list[tuple[str, TravelMode, tuple, tuple]]:
    rnd = random.Random(seed)
    out, tries = [], 0
    cities = list(PLACES)
    while len(out) < n and tries < n * 40:
        tries += 1
        city = cities[len(out) % len(cities)] if rnd.random() < 0.8 else rnd.choice(cities)
        mode = MODES[len(out) % len(MODES)]
        a, b = rnd.sample(PLACES[city], 2)
        km = _dist_m(a[1:], b[1:]) / 1000
        lo, hi = TRIP_KM[mode]
        if lo <= km <= hi:
            out.append((city, mode, a, b))
    return out


def _bad_level(fastest) -> int:
    """Same rule as the cards: step up CPCB bands until the fastest route is above the
    level for at most 70% of its time."""
    total = fastest.duration_s / 60
    for lvl in (90, 120, 250):
        if _mins_above(fastest, lvl) <= total * 0.7:
            return lvl
    return 250


def _mins_above(route, lvl) -> float:
    return sum(s.duration_s / 60 for s in route.segments if s.pm25 is not None and s.pm25 > lvl)


def _context_min(route) -> tuple[float, float]:
    """Minutes beside parks/water and beside busy main roads (from the street layer)."""
    green = sum(sg.duration_s / 60 * sg.beside_green for sg in route.segments)
    road = sum(sg.duration_s / 60 * sg.beside_busy_road for sg in route.segments)
    return round(green, 1), round(road, 1)


async def run_benchmark(app, n: int) -> dict:
    s = app.state.settings
    providers, aq, env = app.state.providers, app.state.aq, app.state.env
    if providers.free:
        raise HTTPException(503, "The benchmark needs the Google providers")
    run_at = datetime.now(timezone.utc)
    sem = asyncio.Semaphore(4)
    usage_total = Usage()

    async def one(city, mode, a, b):
        async with sem:
            req = RouteRequest(origin=LatLng(lat=a[1], lng=a[2]), destination=LatLng(lat=b[1], lng=b[2]),
                               mode=mode, preference=Preference.CLEANEST_AIR)
            try:
                resp = await plan_routes(req, providers, aq, s, env)
            except Exception as e:  # one bad trip must not stop the run
                log.warning("benchmark trip failed: %s", e)
                return None
            for k in ("routes_calls", "aq_current_calls", "aq_forecast_calls"):
                setattr(usage_total, k, getattr(usage_total, k) + getattr(resp.usage, k))
            if not resp.routes:
                return None
            fast = next(r for r in resp.routes if r.id == resp.fastest_id)
            rec = next(r for r in resp.routes if r.id == resp.recommended_id)
            lvl = _bad_level(fast)
            ours = [(p.lat, p.lng) for sg in rec.segments for p in sg.path]
            base = [(p.lat, p.lng) for sg in fast.segments for p in sg.path] if fast.id != rec.id else []
            fid = {}
            for pins in (3, 8):
                via = waypoints(ours, base, mode.value, pins)
                if not via:
                    fid[pins] = None
                    continue
                try:
                    u = Usage()
                    got = await providers.routes.compute_routes(
                        (a[1], a[2]), (b[1], b[2]), mode, alternatives=False, via=via, departure_time=None, usage=u)
                    usage_total.routes_calls += u.routes_calls
                    fid[pins] = overlap(got[0].points, ours) if got else None
                except Exception as e:
                    log.warning("fidelity check failed: %s", e)
                    fid[pins] = None
            g_f, r_f = _context_min(fast)
            g_c, r_c = _context_min(rec)
            return {
                "run_at": run_at, "city": city, "mode": mode.value, "origin": a[0], "destination": b[0],
                "routes": len(resp.routes), "fastest_min": round(fast.duration_s / 60, 1),
                "chosen_min": round(rec.duration_s / 60, 1), "fastest_pm25": fast.mean_pm25, "chosen_pm25": rec.mean_pm25,
                "fastest_bad_min": round(_mins_above(fast, lvl), 1), "chosen_bad_min": round(_mins_above(rec, lvl), 1),
                "bad_level": lvl, "chosen_green_min": g_c, "fastest_green_min": g_f,
                "chosen_road_min": r_c, "fastest_road_min": r_f, "differs": rec.id != fast.id,
                "fidelity3": None if fid[3] is None else round(fid[3], 3),
                "fidelity8": None if fid[8] is None else round(fid[8], 3),
            }

    rows = [r for r in await asyncio.gather(*(one(*t) for t in pick_trips(n))) if r]
    if rows:
        async with app.state.db.engine.begin() as c:
            await c.execute(trips.insert(), rows)
    try:
        await app.state.spend.record(usage_total, None, search=False)
    except Exception:
        log.exception("could not record benchmark spend")
    return {"trips": len(rows), "routes_calls": usage_total.routes_calls, "aq_calls": usage_total.aq_current_calls}


def summarize_trips(rows: list[dict]) -> dict:
    if not rows:
        return {"trips": 0}
    med = lambda v: round(statistics.median(v), 1) if v else None  # noqa: E731
    diff = [r for r in rows if r["differs"] and r["fastest_pm25"] and r["chosen_pm25"]]
    cleaner = [100 * (r["fastest_pm25"] - r["chosen_pm25"]) / r["fastest_pm25"] for r in diff]
    ug = [r["fastest_pm25"] - r["chosen_pm25"] for r in diff]
    bad_saved = [r["fastest_bad_min"] - r["chosen_bad_min"] for r in diff if r["fastest_bad_min"] is not None]
    extra = [r["chosen_min"] - r["fastest_min"] for r in diff]
    road_saved = [r["fastest_road_min"] - r["chosen_road_min"] for r in diff]
    f3 = [r["fidelity3"] for r in rows if r["fidelity3"] is not None]
    f8 = [r["fidelity8"] for r in rows if r["fidelity8"] is not None]
    by_city: dict[str, dict] = {}
    for c in sorted({r["city"] for r in rows}):
        cr = [r for r in rows if r["city"] == c]
        cd = [r for r in cr if r in diff]
        by_city[c] = {
            "trips": len(cr),
            "cleaner_found_pct": round(100 * len(cd) / len(cr), 0),
            "median_cleaner_pct": med([100 * (r["fastest_pm25"] - r["chosen_pm25"]) / r["fastest_pm25"] for r in cd]),
            "median_extra_min": med([r["chosen_min"] - r["fastest_min"] for r in cd]),
        }
    return {
        "trips": len(rows),
        "runs": len({r["run_at"] for r in rows}),
        "cleaner_found_pct": round(100 * len(diff) / len(rows), 1),
        "median_cleaner_pct": med(cleaner),
        "best_cleaner_pct": round(max(cleaner), 1) if cleaner else None,
        "median_cleaner_ugm3": med(ug),
        "median_extra_min": med(extra),
        "median_bad_min_avoided": med(bad_saved),
        "median_busy_road_min_avoided": med(road_saved),
        "fidelity_phone_median_pct": med([100 * x for x in f3]),
        "fidelity_computer_median_pct": med([100 * x for x in f8]),
        "fidelity_computer_90_pct": round(100 * sum(1 for x in f8 if x >= 0.9) / len(f8), 1) if f8 else None,
        "by_city": by_city,
    }


@router.post("/api/validation/benchmark", include_in_schema=False)
async def benchmark_run(request: Request, n: int = 45, x_validation_token: str = Header(default="")):
    s = request.app.state.settings
    if not s.validation_token or x_validation_token != s.validation_token:
        raise HTTPException(403, "Not allowed")
    return await run_benchmark(request.app, max(1, min(n, 120)))


async def load_summary(engine) -> dict:
    async with engine.connect() as c:
        rows = [dict(r._mapping) for r in (await c.execute(sa.select(trips))).all()]
    return summarize_trips(rows)
