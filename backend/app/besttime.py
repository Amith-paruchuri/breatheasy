"""Best time to leave: the same route, leaving now or in 30, 60, 90 or 120 minutes.

In Indian cities PM2.5 often changes far more over a couple of hours (traffic peaks,
the evening inversion, wind) than between two streets, so when you leave can matter
more than which way you go. For a route the user is looking at, we read the hourly
forecast along it for each departure time and give the time-weighted average PM2.5.

Smog changes slowly across a city, so a coarse grid (at most ~12 cells) is enough:
about a dozen forecast calls per route, each covering every hour needed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .models import LatLng, TravelMode, Usage
from .services.planner import IST

log = logging.getLogger("breatheasy.besttime")
router = APIRouter()

OFFSETS_MIN = (0, 30, 60, 90, 120)
MAX_CELLS = 12


class TimePoint(BaseModel):
    lat: float
    lng: float
    offset_s: float = Field(ge=0)  # time from departure to reach this point
    duration_s: float = Field(ge=0)  # time spent around this point


class BestTimeRequest(BaseModel):
    points: list[TimePoint] = Field(min_length=1, max_length=80)
    mode: TravelMode = TravelMode.WALK


class Slot(BaseModel):
    offset_min: int
    depart: str  # "18:40" IST
    mean_pm25: float | None


class BestTimeResponse(BaseModel):
    slots: list[Slot]
    best_offset_min: int | None
    cleaner_pct: float | None  # best slot vs leaving now
    source: str | None


def points_from_route(route, max_points: int = 60) -> list[TimePoint]:
    """Sample a RouteOut's segments into at most max_points timed points."""
    segs = [sg for sg in route.segments if sg.path]
    step = max(1, len(segs) // max_points + (1 if len(segs) % max_points else 0))
    out = []
    for i in range(0, len(segs), step):
        group = segs[i : i + step]
        mid = group[len(group) // 2]
        p = mid.path[len(mid.path) // 2]
        out.append(TimePoint(lat=p.lat, lng=p.lng, offset_s=group[0].arrival_offset_s,
                             duration_s=sum(g.duration_s for g in group)))
    return out


async def best_time(points: list[TimePoint], aq, now: datetime | None = None) -> tuple[BestTimeResponse, Usage]:
    now = now or datetime.now(IST)
    usage = Usage()
    coords = [(p.lat, p.lng) for p in points]
    scale = 2
    while scale < 64 and len({aq.cell_of(la, ln, scale) for la, ln in coords}) > MAX_CELLS:
        scale *= 2
    queries, index = [], []
    for k, off in enumerate(OFFSETS_MIN):
        dep = now + timedelta(minutes=off)
        for j, p in enumerate(points):
            queries.append((p.lat, p.lng, dep + timedelta(seconds=p.offset_s)))
            index.append((k, j))
    # current_window_min=0: only the present hour uses current conditions, later hours
    # use the forecast (otherwise everything within 2 h would read "current").
    readings = await aq.lookup(queries, now, usage, scale=scale, current_window_min=0)
    sums = [[0.0, 0.0] for _ in OFFSETS_MIN]
    for (k, j), r in zip(index, readings):
        if r is not None and r.pm25 is not None:
            w = max(points[j].duration_s, 1.0)
            sums[k][0] += r.pm25 * w
            sums[k][1] += w
    total_w = sum(max(p.duration_s, 1.0) for p in points)
    slots = []
    for k, off in enumerate(OFFSETS_MIN):
        s, w = sums[k]
        mean = round(s / w, 1) if w >= 0.6 * total_w else None  # need most of the route covered
        slots.append(Slot(offset_min=off, depart=(now + timedelta(minutes=off)).strftime("%H:%M"), mean_pm25=mean))
    have = [x for x in slots if x.mean_pm25 is not None]
    best = min(have, key=lambda x: (x.mean_pm25, x.offset_min)) if have else None
    now_v = slots[0].mean_pm25
    pct = round(100 * (now_v - best.mean_pm25) / now_v, 1) if best and now_v else None
    return BestTimeResponse(slots=slots, best_offset_min=best.offset_min if best else None, cleaner_pct=pct,
                            source=usage.aq_source), usage


@router.post("/api/best-time", response_model=BestTimeResponse)
async def best_time_endpoint(body: BestTimeRequest, request: Request):
    from .web import client_ip

    app = request.app
    if not app.state.route_limiter.check(client_ip(request)):
        raise HTTPException(429, "Too many requests. Try again in a minute.")
    guard = app.state.spend
    if await guard.over_budget():
        raise HTTPException(503, "Best time to leave is paused for today.")
    resp, usage = await best_time(body.points, app.state.aq)
    try:
        await guard.record(usage, body.mode, search=False)
    except Exception:
        log.exception("could not record best-time spend")
    return resp
