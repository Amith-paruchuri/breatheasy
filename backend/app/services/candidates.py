"""Candidate route generation (Challenge 1 in the proposal).

1. Ask the routing engine for its primary route plus alternatives.
2. Optionally ask for extra routes forced through "via" waypoints offset to
   either side of the fastest route's midpoint. These explore corridors the
   engine would not normally suggest.
3. Ask for routes through parks and lakes near the trip ("green corridors"),
   chosen from the OpenStreetMap environment layer within the time budget.
4. Drop near-duplicates by geometric overlap.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from ..config import Settings
from ..geo import Point, bearing_deg, destination_point, haversine_m, overlap_fraction
from ..models import TravelMode, Usage
from ..providers.base import ProviderError, RawRoute, RouteProvider


@dataclass
class Candidate:
    route: RawRoute
    source: str  # primary | alternative | detour | green
    via_name: str = ""  # the park/lake a green-corridor route was steered through


# Rough door-to-door speeds used only to turn a time budget into a search distance.
MODE_SPEED_MPS = {TravelMode.WALK: 1.3, TravelMode.BICYCLE: 4.0, TravelMode.TWO_WHEELER: 7.0, TravelMode.DRIVE: 6.0}


def detour_waypoints(route: RawRoute, origin: Point, dest: Point, s: Settings) -> list[Point]:
    if s.detour_count <= 0 or len(route.points) < 2:
        return []
    od = haversine_m(origin, dest)
    offset = min(s.detour_offset_max_m, max(s.detour_offset_min_m, od * s.detour_offset_frac))
    brg = bearing_deg(origin, dest)
    fractions = [0.5] if s.detour_count <= 2 else [0.33, 0.67]
    pts = route.points
    out: list[Point] = []
    for f in fractions:
        anchor = pts[min(len(pts) - 1, int(len(pts) * f))]
        out.append(destination_point(anchor, brg + 90, offset))
        out.append(destination_point(anchor, brg - 90, offset))
    return out


async def generate_candidates(
    provider: RouteProvider,
    origin: Point,
    dest: Point,
    mode: TravelMode,
    departure: datetime | None,
    explore_detours: bool,
    s: Settings,
    usage: Usage,
    env=None,
    max_extra_min: float = 0.0,
) -> tuple[list[Candidate], list[str]]:
    warnings: list[str] = []
    base = await provider.compute_routes(
        origin, dest, mode, alternatives=True, via=None, departure_time=departure, usage=usage
    )
    if not base:
        raise ProviderError(
            f"No {mode.value.replace('_', ' ').lower()} route found between these points. "
            "Bicycle and two-wheeler coverage varies by area; try another mode.",
            404,
        )
    cands = [Candidate(r, "primary" if i == 0 else "alternative") for i, r in enumerate(base)]

    long_trip = haversine_m(origin, dest) > s.detour_max_trip_km * 1000
    if explore_detours and not long_trip and s.detour_count > 0 and len(cands) < s.max_candidates:
        fastest = min(base, key=lambda r: r.duration_s)
        wps = detour_waypoints(fastest, origin, dest, s)

        async def one(wp: Point) -> RawRoute | None:
            try:
                rs = await provider.compute_routes(
                    origin, dest, mode, alternatives=False, via=[wp], departure_time=departure, usage=usage
                )
                return rs[0] if rs else None
            except ProviderError:
                return None  # waypoint may be unroutable (river, airport, etc.)

        extra = await asyncio.gather(*(one(w) for w in wps))
        failed = sum(1 for r in extra if r is None)
        if failed and failed == len(wps):
            warnings.append("Detour exploration found no routable corridors for this trip.")
        # discard absurd detours (more than 2x the fastest duration)
        cands += [Candidate(r, "detour") for r in extra if r and r.duration_s <= 2 * fastest.duration_s]

    # Green corridors: steer through big parks / lakes near the trip, within the time budget.
    if explore_detours and env is not None and not env.empty and s.green_detours > 0 and max_extra_min > 0:
        fastest = min(base, key=lambda r: r.duration_s)
        max_extra_m = max_extra_min * 60 * MODE_SPEED_MPS[mode]
        greens = env.green_waypoints(
            origin, dest, max_extra_m, fastest.points, count=s.green_detours, min_area_m2=s.green_detour_min_area_m2
        )

        async def via(wp: Point) -> RawRoute | None:
            try:
                rs = await provider.compute_routes(
                    origin, dest, mode, alternatives=False, via=[wp], departure_time=departure, usage=usage
                )
                return rs[0] if rs else None
            except ProviderError:
                return None

        routed = await asyncio.gather(*(via(pt) for pt, _ in greens))
        limit_s = fastest.duration_s + max_extra_min * 60 * 1.25
        cands += [
            Candidate(r, "green", name) for r, (_, name) in zip(routed, greens) if r and r.duration_s <= limit_s
        ]

    # Keep the engine's own routes first, then green corridors, then plain detours.
    priority = {"primary": 0, "alternative": 1, "green": 2, "detour": 3}
    cands.sort(key=lambda c: priority.get(c.source, 9))
    kept: list[Candidate] = []
    for c in cands:
        if any(
            overlap_fraction(c.route.points, k.route.points) >= s.duplicate_overlap
            and overlap_fraction(k.route.points, c.route.points) >= s.duplicate_overlap
            for k in kept
        ):
            continue
        kept.append(c)
        if len(kept) >= s.max_candidates:
            break
    return kept, warnings
