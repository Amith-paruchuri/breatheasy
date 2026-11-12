"""Validation against official monitoring stations, and anonymous usage counts.

Validation: every few hours, a scheduler calls POST /api/validation/run. For a sample
of CPCB stations (live readings from data.gov.in), we compare the station's 24-hour
average PM2.5 with what Breatheasy would have said for that exact spot:

- google:   Google's air-quality model, averaged over the same 24 hours (history API)
- adjusted: the same value after Breatheasy's street adjustment (busy road nearby: up,
            beside a park or lake: down), which is what route cards use

GET /api/validation/summary turns the stored pairs into plain numbers: typical error,
bias, correlation, and the most important one for routing: how often the model puts
two stations in the same city in the right order (which one is dirtier).

Usage counts: one row per day, event and city. No user, no location, no IP.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import statistics
from datetime import datetime, timezone

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("breatheasy.validation")
router = APIRouter()

metadata = sa.MetaData()
samples = sa.Table(
    "validation_samples",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("run_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("station", sa.String(200), nullable=False),
    sa.Column("city", sa.String(100), nullable=False),
    sa.Column("state", sa.String(100), nullable=False),
    sa.Column("lat", sa.Float, nullable=False),
    sa.Column("lng", sa.Float, nullable=False),
    sa.Column("station_updated", sa.String(40)),
    sa.Column("station_pm25", sa.Float, nullable=False),  # CPCB 24-hour average
    sa.Column("google_pm25", sa.Float, nullable=False),  # Google model, same 24 hours
    sa.Column("adjusted_pm25", sa.Float, nullable=False),  # after Breatheasy's street adjustment
    sa.Column("hours", sa.Integer, nullable=False),
    sa.Column("near_road", sa.Boolean, nullable=False),
    sa.Column("near_green", sa.Boolean, nullable=False),
    sa.Column("street_layer", sa.Boolean, nullable=False),  # was street context available here
)
usage_counts = sa.Table(
    "usage_counts",
    metadata,
    sa.Column("day", sa.String(10), primary_key=True),
    sa.Column("event", sa.String(24), primary_key=True),
    sa.Column("city", sa.String(40), primary_key=True),
    sa.Column("n", sa.Integer, nullable=False, server_default="0"),
)

DATAGOV_URL = "https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"
AQ_HISTORY_URL = "https://airquality.googleapis.com/v1/history:lookup"
FOCUS = ("Delhi", "Mumbai", "Kolkata", "Bengaluru", "Hyderabad")
CITY_ALIASES = {"bengaluru": "Bengaluru", "bangalore": "Bengaluru", "kolkata": "Kolkata", "mumbai": "Mumbai",
                "navi mumbai": "Mumbai", "thane": "Mumbai", "hyderabad": "Hyderabad", "delhi": "Delhi",
                "new delhi": "Delhi", "gurugram": "Delhi", "noida": "Delhi", "ghaziabad": "Delhi",
                "faridabad": "Delhi", "greater noida": "Delhi"}


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x >= 0 else None


def city_group(city: str, state: str = "") -> str:
    c = CITY_ALIASES.get((city or "").strip().lower())
    if c:
        return c
    return "Delhi" if (state or "").strip().lower() == "delhi" else (city or "Other").strip()


async def fetch_stations(http: httpx.AsyncClient, api_key: str) -> list[dict]:
    """Latest PM2.5 (24-hour average) for every CPCB station on data.gov.in."""
    out, offset = [], 0
    while offset < 5000:
        r = await http.get(DATAGOV_URL, params={
            "api-key": api_key, "format": "json", "limit": 500, "offset": offset,
            "filters[pollutant_id]": "PM2.5",
        })
        r.raise_for_status()
        recs = r.json().get("records", []) or []
        for x in recs:
            lat, lng = _num(x.get("latitude")), _num(x.get("longitude"))
            pm = _num(x.get("avg_value", x.get("pollutant_avg")))
            if lat is None or lng is None or pm is None or not (6 < lat < 38 and 68 < lng < 98):
                continue
            out.append({"station": x.get("station", "")[:200], "city": (x.get("city") or "")[:100],
                        "state": (x.get("state") or "")[:100], "lat": lat, "lng": lng, "pm25": pm,
                        "updated": str(x.get("last_update") or "")[:40]})
        if len(recs) < 500:
            break
        offset += 500
    return out


async def google_24h(http: httpx.AsyncClient, key: str, lat: float, lng: float) -> tuple[float, int] | None:
    body = {"hours": 24, "pageSize": 24, "location": {"latitude": lat, "longitude": lng},
            "extraComputations": ["POLLUTANT_CONCENTRATION"], "universalAqi": False}
    r = await http.post(AQ_HISTORY_URL, json=body, headers={"X-Goog-Api-Key": key})
    if r.status_code >= 400:
        log.warning("AQ history %s: %s", r.status_code, r.text[:200])
        return None
    vals = []
    for h in r.json().get("hoursInfo", []) or []:
        for p in h.get("pollutants", []) or []:
            if p.get("code") == "pm25":
                v = _num((p.get("concentration") or {}).get("value"))
                if v is not None:
                    vals.append(v)
    return (sum(vals) / len(vals), len(vals)) if vals else None


def pick_stations(stations: list[dict], n: int) -> list[dict]:
    """All stations in the five focus cities (up to ~60%), the rest spread over India."""
    focus = [s for s in stations if city_group(s["city"], s["state"]) in FOCUS]
    other = [s for s in stations if s not in focus]
    random.shuffle(focus)
    random.shuffle(other)
    k = min(len(focus), int(n * 0.6))
    return focus[:k] + other[: max(0, n - k)]


async def run_once(app, max_stations: int) -> dict:
    s = app.state.settings
    if not s.datagov_api_key:
        raise HTTPException(503, "DATAGOV_API_KEY is not set")
    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=20)) as http:
        try:
            stations = await fetch_stations(http, s.datagov_api_key)
        except httpx.HTTPStatusError as e:
            log.warning("data.gov.in %s: %s", e.response.status_code, e.response.text[:300])
            raise HTTPException(502, f"data.gov.in answered {e.response.status_code}: {e.response.text[:200]}") from e
        except httpx.HTTPError as e:
            log.warning("data.gov.in unreachable: %r", e)
            raise HTTPException(502, f"data.gov.in did not answer in time ({type(e).__name__}); try again") from e
        if not stations:
            raise HTTPException(502, "data.gov.in returned no PM2.5 readings")
        chosen = pick_stations(stations, max_stations)
        sem = asyncio.Semaphore(8)
        run_at = datetime.now(timezone.utc)

        async def one(st):
            async with sem:
                g = await google_24h(http, s.google_maps_server_key, st["lat"], st["lng"])
            if g is None:
                return None
            layer = app.state.env.at((st["lat"], st["lng"]))
            road = green = False
            if not layer.empty:
                areas, roads = layer.near((st["lat"], st["lng"]))
                road = bool(roads)
                green = any(a.kind in ("green", "water") for a in areas)
            factor = max(0.5, 1 + s.street_adjust_busy_road * road - s.street_adjust_green * green)
            return {"run_at": run_at, "station": st["station"], "city": st["city"] or "", "state": st["state"] or "",
                    "lat": st["lat"], "lng": st["lng"], "station_updated": st["updated"], "station_pm25": st["pm25"],
                    "google_pm25": round(g[0], 2), "adjusted_pm25": round(g[0] * factor, 2), "hours": g[1],
                    "near_road": road, "near_green": green, "street_layer": not layer.empty}

        rows = [r for r in await asyncio.gather(*(one(st) for st in chosen)) if r]
    if rows:
        async with app.state.db.engine.begin() as c:
            await c.execute(samples.insert(), rows)
    try:  # count the Google calls against the daily spending cap
        from .models import Usage

        await app.state.spend.record(Usage(aq_current_calls=len(chosen), aq_source="google"), None, search=False)
    except Exception:
        log.exception("could not record validation spend")
    return {"stations_available": len(stations), "sampled": len(chosen), "stored": len(rows)}


# ---------- statistics ----------
def _pearson(x, y):
    if len(x) < 3:
        return None
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return None if sx == 0 or sy == 0 else sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def _errors(rows, col):
    e = [r[col] - r["station_pm25"] for r in rows]
    if not e:
        return None
    ae = sorted(abs(v) for v in e)
    rel = [abs(r[col] - r["station_pm25"]) / r["station_pm25"] for r in rows if r["station_pm25"] > 0]
    return {
        "mae": round(statistics.fmean(ae), 1),
        "median_abs_error": round(ae[len(ae) // 2], 1),
        "bias": round(statistics.fmean(e), 1),
        "within_25pct": round(100 * sum(1 for v in rel if v <= 0.25) / len(rel), 1) if rel else None,
        "r": (lambda v: round(v, 2) if v is not None else None)(_pearson([r[col] for r in rows], [r["station_pm25"] for r in rows])),
    }


def _order_agreement(rows, col, min_gap=10.0):
    """Within each run and city: for station pairs whose official readings differ by at
    least min_gap µg/m³, how often does the model say the same one is dirtier?"""
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((r["run_at"], city_group(r["city"], r["state"])), []).append(r)
    agree = total = 0
    for g in groups.values():
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                d = g[i]["station_pm25"] - g[j]["station_pm25"]
                if abs(d) < min_gap:
                    continue
                total += 1
                if (g[i][col] - g[j][col]) * d > 0:
                    agree += 1
    return {"pairs": total, "agree_pct": round(100 * agree / total, 1) if total else None}


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {"samples": 0}
    by_city: dict[str, list] = {}
    for r in rows:
        by_city.setdefault(city_group(r["city"], r["state"]), []).append(r)
    cities = {
        c: {"samples": len(v), "stations": len({x["station"] for x in v}), "google": _errors(v, "google_pm25"),
            "adjusted": _errors(v, "adjusted_pm25"), "order_adjusted": _order_agreement(v, "adjusted_pm25")}
        for c, v in sorted(by_city.items(), key=lambda kv: -len(kv[1]))
        if c in FOCUS or len(v) >= 20
    }
    street = [r for r in rows if r["street_layer"]]
    road = [r for r in street if r["near_road"]]
    green = [r for r in street if r["near_green"] and not r["near_road"]]
    scatter = [{"s": round(r["station_pm25"]), "m": round(r["adjusted_pm25"])} for r in rows[-600:]]
    return {
        "samples": len(rows),
        "stations": len({r["station"] for r in rows}),
        "runs": len({r["run_at"] for r in rows}),
        "first": min(r["run_at"] for r in rows).isoformat(),
        "last": max(r["run_at"] for r in rows).isoformat(),
        "google": _errors(rows, "google_pm25"),
        "adjusted": _errors(rows, "adjusted_pm25"),
        "order_google": _order_agreement(rows, "google_pm25"),
        "order_adjusted": _order_agreement(rows, "adjusted_pm25"),
        "street": {
            "near_road": {"n": len(road), "google": _errors(road, "google_pm25"), "adjusted": _errors(road, "adjusted_pm25")},
            "near_green": {"n": len(green), "google": _errors(green, "google_pm25"), "adjusted": _errors(green, "adjusted_pm25")},
        },
        "cities": cities,
        "scatter": scatter,
    }


@router.post("/api/validation/run", include_in_schema=False)
async def validation_run(request: Request, x_validation_token: str = Header(default="")):
    s = request.app.state.settings
    if not s.validation_token or x_validation_token != s.validation_token:
        raise HTTPException(403, "Not allowed")
    return await run_once(request.app, s.validation_stations)


@router.get("/api/validation/summary")
async def validation_summary(request: Request):
    async with request.app.state.db.engine.connect() as c:
        rows = [dict(r._mapping) for r in (await c.execute(sa.select(samples).order_by(samples.c.run_at))).all()]
    out = summarize(rows)
    from .benchmark import load_summary

    out["benchmark"] = await load_summary(request.app.state.db.engine)
    return out


# ---------- usage counts ----------
EVENTS = {"search", "agent", "maps_open", "share", "shared_open"}
_CITY_BOXES = {  # same areas as the street layer
    "Delhi-NCR": (28.20, 76.80, 28.95, 77.75), "Mumbai": (18.88, 72.77, 19.30, 73.10),
    "Kolkata": (22.40, 88.20, 22.70, 88.50), "Bengaluru": (12.80, 77.45, 13.15, 77.80),
    "Hyderabad": (17.25, 78.30, 17.60, 78.65),
}


def city_of(lat: float | None, lng: float | None) -> str:
    if lat is None or lng is None:
        return "Unknown"
    for name, (s_, w, n, e) in _CITY_BOXES.items():
        if s_ <= lat <= n and w <= lng <= e:
            return name
    return "Rest of India" if 6.5 <= lat <= 37.2 and 68 <= lng <= 97.5 else "Outside India"


async def count(engine, event: str, city: str) -> None:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        async with engine.begin() as c:
            res = await c.execute(
                usage_counts.update()
                .where(usage_counts.c.day == day, usage_counts.c.event == event, usage_counts.c.city == city)
                .values(n=usage_counts.c.n + 1)
            )
            if res.rowcount == 0:
                try:
                    async with c.begin_nested():
                        await c.execute(usage_counts.insert().values(day=day, event=event, city=city, n=1))
                except sa.exc.IntegrityError:
                    await c.execute(
                        usage_counts.update()
                        .where(usage_counts.c.day == day, usage_counts.c.event == event, usage_counts.c.city == city)
                        .values(n=usage_counts.c.n + 1)
                    )
    except Exception:  # counting must never break the app
        log.exception("usage count failed")


class EventIn(BaseModel):
    event: str
    lat: float | None = None
    lng: float | None = None


@router.post("/api/event", status_code=204)
async def post_event(e: EventIn, request: Request):
    if e.event not in {"maps_open", "share", "shared_open"}:
        raise HTTPException(400, "Unknown event")
    # only the city area is kept, never the coordinates
    await count(request.app.state.db.engine, e.event, city_of(e.lat, e.lng))


@router.get("/api/stats")
async def stats(request: Request):
    async with request.app.state.db.engine.connect() as c:
        rows = [dict(r._mapping) for r in (await c.execute(sa.select(usage_counts))).all()]
    totals: dict[str, int] = {}
    by_city: dict[str, dict[str, int]] = {}
    by_day: dict[str, dict[str, int]] = {}
    for r in rows:
        totals[r["event"]] = totals.get(r["event"], 0) + r["n"]
        by_city.setdefault(r["city"], {}).setdefault(r["event"], 0)
        by_city[r["city"]][r["event"]] += r["n"]
        by_day.setdefault(r["day"], {}).setdefault(r["event"], 0)
        by_day[r["day"]][r["event"]] += r["n"]
    return {
        "totals": totals,
        "by_city": by_city,
        "by_day": dict(sorted(by_day.items())),
        "since": min(by_day) if by_day else None,
        "note": "Anonymous counts only: event, day and city area. No accounts, locations or IP addresses are stored.",
    }
