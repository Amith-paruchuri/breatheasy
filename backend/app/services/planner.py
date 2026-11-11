"""Orchestrates one route request end to end."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import Settings
from ..geo import haversine_m
from ..models import (
    Comparison,
    DataInfo,
    Hotspot,
    LatLng,
    RouteOut,
    RouteRequest,
    RouteResponse,
    SegmentOut,
    Usage,
)
from ..aqi import category as aqi_category
from ..aqi import compute_aqi
from ..environment import EnvironmentLayer, highlights
from ..budget import google_cost
from ..models import Highlight, Preference, TravelMode
from ..providers import Providers
from ..providers.base import ProviderError
from .airquality import AQService
from .candidates import generate_candidates
from .exposure import compute_exposure
from .ranking import Scored, pick
from .sampling import build_timed_path, split_segments

IST = timezone(timedelta(hours=5, minutes=30))

_CAND_CACHE: dict[tuple, tuple[float, list, list[str], str | None]] = {}


async def _candidates_cached(
    req: RouteRequest,
    providers: Providers,
    departure,
    s: Settings,
    usage: Usage,
    env,
    max_extra: float,
    route_departure: datetime | None = None,
):
    # Candidates depend on the time budget only through which parks are in reach, so
    # bucket it: moving the slider re-ranks from cache instead of new Routes calls.
    bucket = next((b for b in (10, 20, 30, 45, 60, 90, 120, 180) if max_extra <= b), 180)
    max_extra = bucket
    cand_departure = route_departure or (departure if req.departure_time else None)
    key = (
        bucket,
        providers.name,
        round(req.origin.lat, 5), round(req.origin.lng, 5),
        round(req.destination.lat, 5), round(req.destination.lng, 5),
        req.mode.value,
        cand_departure.isoformat() if cand_departure else None,
        req.explore_detours,
    )
    hit = _CAND_CACHE.get(key)
    if hit and hit[0] > time.monotonic():
        usage.routes_source = hit[3]
        if hit[3] == "open" and providers.name == "google":
            usage.fallback = True
        return hit[1], list(hit[2])
    o = (req.origin.lat, req.origin.lng)
    d = (req.destination.lat, req.destination.lng)
    cands, warns = await generate_candidates(
        providers.routes, o, d, req.mode, cand_departure, req.explore_detours, s, usage,
        env=env, max_extra_min=max_extra,
    )
    usage.routes_source = usage.routes_source or providers.name
    if s.route_cache_ttl_s > 0:
        if len(_CAND_CACHE) > 2000:
            _CAND_CACHE.clear()
        _CAND_CACHE[key] = (time.monotonic() + s.route_cache_ttl_s, cands, warns, usage.routes_source)
    return cands, list(warns)


def _ll(p) -> LatLng:
    return LatLng(lat=round(p[0], 6), lng=round(p[1], 6))


MODE_WORDS = {
    TravelMode.WALK: "walking",
    TravelMode.BICYCLE: "cycling",
    TravelMode.TWO_WHEELER: "two-wheeler",
    TravelMode.DRIVE: "car",
}


def trip_limit_km(mode: TravelMode, s: Settings) -> float:
    return {
        TravelMode.WALK: s.max_trip_km_walk,
        TravelMode.BICYCLE: s.max_trip_km_bicycle,
        TravelMode.TWO_WHEELER: s.max_trip_km_two_wheeler,
        TravelMode.DRIVE: s.max_trip_km_drive,
    }[mode]


def check_trip_length(req: RouteRequest, s: Settings) -> None:
    km = haversine_m((req.origin.lat, req.origin.lng), (req.destination.lat, req.destination.lng)) / 1000
    limit = trip_limit_km(req.mode, s)
    if km <= limit:
        return
    suggest = [m.value for m in (TravelMode.BICYCLE, TravelMode.TWO_WHEELER, TravelMode.DRIVE) if km <= trip_limit_km(m, s)]
    if req.mode in (TravelMode.WALK, TravelMode.BICYCLE) and suggest:
        msg = (
            f"These places are about {km:.0f} km apart, too far for {MODE_WORDS[req.mode]} "
            f"(up to {limit:.0f} km). Try another way of travelling, or check the start point."
        )
    else:
        msg = f"These places are about {km:.0f} km apart. Breatheasy plans trips within {s.region_name}; check the start and destination."
    raise ProviderError(msg, 422, code="too_far", suggest_modes=suggest)


def in_region(p: LatLng, s: Settings) -> bool:
    return s.region_south <= p.lat <= s.region_north and s.region_west <= p.lng <= s.region_east


def _adjusted(r, factor: float):
    """Scale every pollutant concentration by a street-level factor."""
    if r is None or abs(factor - 1.0) < 1e-9:
        return r
    f = lambda v: None if v is None else round(v * factor, 2)  # noqa: E731
    return replace(r, pm25=f(r.pm25), pm10=f(r.pm10), no2=f(r.no2), o3=r.o3, co_mg=f(r.co_mg), so2=f(r.so2))


async def plan_routes(
    req: RouteRequest,
    providers: Providers,
    aq: AQService,
    s: Settings,
    env: EnvironmentLayer | None = None,
    force_open: bool = False,
    open_reason: str | None = None,
    route_departure: datetime | None = None,
) -> RouteResponse:
    usage = Usage()
    if force_open and hasattr(providers.routes, "secondary"):
        usage.routes_source = "open"  # daily Google budget reached: free open data only
    warnings: list[str] = []
    now = datetime.now(timezone.utc)
    departure = req.departure_time or now
    if departure.tzinfo is None:
        departure = departure.replace(tzinfo=IST)
    if departure < now - timedelta(minutes=5):
        departure = now
        warnings.append("Departure time was in the past; planned for now instead.")
    if req.max_extra_minutes is not None:
        max_extra = req.max_extra_minutes
    elif req.preference == Preference.CLEANEST_AIR:
        max_extra = s.cleanest_air_default_extra_minutes
    else:
        max_extra = s.default_max_extra_minutes
    use_env = env is not None and not env.empty

    for label, p in (("Origin", req.origin), ("Destination", req.destination)):
        if not in_region(p, s):
            warnings.append(f"{label} is outside the {s.region_name} pilot area; results are less tested there.")

    check_trip_length(req, s)
    cands, cw = await _candidates_cached(
        req, providers, departure, s, usage, env if use_env else None, max_extra, route_departure=route_departure
    )
    warnings += cw

    # Segment every candidate (coarser on long routes so a search stays fast),
    # then do ONE batched AQ lookup across all of them.
    seg_lists = []
    for c in cands:
        tp = build_timed_path(c.route)
        spacing = max(s.sample_spacing_m, tp.length_m / max(1, s.max_segments_per_route))
        seg_lists.append(split_segments(tp, spacing))
    queries = [
        (seg.mid[0], seg.mid[1], departure + timedelta(seconds=seg.mid_s)) for segs in seg_lists for seg in segs
    ]
    vehicle = req.mode in (TravelMode.DRIVE, TravelMode.TWO_WHEELER)
    scale = aq.choose_scale([(q[0], q[1]) for q in queries], s.aq_vehicle_scale if vehicle else 1)
    readings_flat = await aq.lookup(queries, now, usage, scale, force_open=force_open)

    # Street context is CPU work: do it off the event loop so other requests keep flowing.
    env_ctx = (
        await asyncio.to_thread(lambda: [env.describe_segments(segs) for segs in seg_lists]) if use_env else None
    )

    routes_out: list[RouteOut] = []
    scored: list[Scored] = []
    i = 0
    oldest: datetime | None = None
    uses_forecast = False
    for n, (cand, segs) in enumerate(zip(cands, seg_lists)):
        raw = readings_flat[i : i + len(segs)]
        i += len(segs)
        # Street-level context from OpenStreetMap: what's beside each stretch.
        if use_env:
            seg_ctx, route_ctx = env_ctx[n]
            factors = [
                max(0.5, 1 + s.street_adjust_busy_road * c.frac_road - s.street_adjust_green * c.frac_green)
                for c in seg_ctx
            ]
        else:
            seg_ctx, route_ctx, factors = [None] * len(segs), None, [1.0] * len(segs)
        rd = [_adjusted(r, f) for r, f in zip(raw, factors)]
        ex = compute_exposure(segs, rd, s.pm25_reference_ugm3)
        seg_aqi = [
            compute_aqi(r.pm25, r.pm10, r.no2, r.o3, r.co_mg, r.so2) if r is not None else None for r in rd
        ]
        w_known = [(a.aqi, seg.duration_s) for a, seg in zip(seg_aqi, segs) if a is not None]
        tot_w = sum(d for _, d in w_known)
        mean_aqi = sum(a * d for a, d in w_known) / tot_w if tot_w > 0 else None
        peak_aqi = max((a for a, _ in w_known), default=None)
        cells = {aq.cell_of(seg.mid[0], seg.mid[1], scale) for seg in segs}
        for r in rd:
            if r is None:
                continue
            if r.kind == "current":
                oldest = r.observed_at if oldest is None else min(oldest, r.observed_at)
            else:
                uses_forecast = True

        seg_out = [
            SegmentOut(
                path=[_ll(p) for p in seg.path],
                duration_s=round(seg.duration_s, 1),
                arrival_offset_s=round(seg.start_s, 1),
                pm25=r.pm25 if r else None,
                pm10=r.pm10 if r else None,
                no2_ppb=r.no2_ppb if r else None,
                uaqi=r.uaqi if r else None,
                aqi=a.aqi if a else None,
                aqi_category=a.category if a else None,
                dominant_pollutant=a.dominant if a else None,
                beside_green=round(c.frac_green, 2) if c else 0.0,
                beside_busy_road=round(c.frac_road, 2) if c else 0.0,
                data_kind=r.kind if r else None,
            )
            for seg, r, a, c in zip(segs, rd, seg_aqi, seg_ctx)
        ]
        notes = highlights(route_ctx, req.mode.value) if route_ctx else []
        hotspots = _hotspots(segs, rd, ex.mean_pm25)
        rid = f"r{n}"
        routes_out.append(
            RouteOut(
                id=rid,
                source=cand.source,
                via=cand.via_name or None,
                labels=cand.route.labels,
                duration_s=round(cand.route.duration_s),
                distance_m=round(cand.route.distance_m),
                encoded_polyline=cand.route.encoded_polyline,
                exposure_pm25=ex.exposure_pm25,
                exposure_pm10=ex.exposure_pm10,
                mean_pm25=ex.mean_pm25,
                peak_pm25=ex.peak_pm25,
                minutes_above_reference=ex.minutes_above_reference,
                delta_exposure_pct=None,
                extra_minutes=0.0,
                within_budget=True,
                coverage=ex.coverage,
                distinct_cells=len(cells),
                mean_aqi=round(mean_aqi) if mean_aqi is not None else None,
                peak_aqi=peak_aqi,
                aqi_category=aqi_category(mean_aqi),
                minutes_green=round(route_ctx.minutes_green + route_ctx.minutes_water, 1) if route_ctx else 0.0,
                minutes_busy_road=round(route_ctx.minutes_busy_road, 1) if route_ctx else 0.0,
                highlights=[Highlight(**h) for h in notes],
                segments=seg_out,
                hotspots=hotspots,
            )
        )
        scored.append(Scored(rid, cand.route.duration_s, ex.exposure_pm25, cells, mean_aqi))

    rec_id, fast_id, comp = pick(
        scored, req.preference, max_extra, s.balanced_pct_per_min, s.meaningful_diff_pct, s.meaningful_aqi_points
    )
    fastest = next(r for r in routes_out if r.id == fast_id)
    for r in routes_out:
        r.extra_minutes = round((r.duration_s - fastest.duration_s) / 60, 1)
        r.within_budget = r.extra_minutes <= max_extra + 1e-6
        if r.exposure_pm25 is not None and fastest.exposure_pm25:
            r.delta_exposure_pct = round((r.exposure_pm25 - fastest.exposure_pm25) / fastest.exposure_pm25 * 100, 1)
        if r.mean_aqi is not None and fastest.mean_aqi is not None:
            r.delta_aqi = r.mean_aqi - fastest.mean_aqi

    # Recommended first, then cleanest air (or least exposure), unknown last, then time.
    if req.preference == Preference.CLEANEST_AIR:
        routes_out.sort(key=lambda r: (r.id != rec_id, r.mean_aqi is None, r.mean_aqi or 0, r.duration_s))
    else:
        routes_out.sort(
            key=lambda r: (r.id != rec_id, r.exposure_pm25 is None, r.exposure_pm25 or 0, r.duration_s)
        )
    if any(r.coverage < 0.8 for r in routes_out):
        warnings.append("Air-quality data was missing for part of at least one route; gaps were filled with that route's average.")

    if force_open:
        warnings.append(
            open_reason
            or "Breatheasy is very busy today, so this search uses free open data "
            "(coarser air quality; route differences are less reliable)."
        )
    elif usage.fallback:
        warnings.append(
            "Google data was unavailable for this request, so it uses open data instead "
            "(coarser air quality; route differences are less reliable)."
        )
    usage.estimated_cost_usd = 0.0 if providers.free else round(google_cost(usage, s, req.mode), 5)
    resp = RouteResponse(
        routes=routes_out,
        recommended_id=rec_id,
        fastest_id=fast_id,
        preference=req.preference,
        max_extra_minutes=max_extra,
        comparison=Comparison(**comp),
        data=DataInfo(
            provider=providers.name,
            routes_source=usage.routes_source,
            aq_source=usage.aq_source,
            mock=s.is_mock,
            departure_time=departure,
            computed_at=now,
            oldest_observation=oldest,
            uses_forecast=uses_forecast,
            resolution_note=providers.note_for(usage.aq_source)
            + (
                " AQI is on India's CPCB scale, estimated from hourly model values (official AQI uses 24-hour averages)."
            )
            + (
                " Adjusted for busy roads and green space using OpenStreetMap (© OpenStreetMap contributors)."
                if use_env and (s.street_adjust_busy_road or s.street_adjust_green)
                else ""
            ),
        ),
        usage=usage,
        warnings=warnings,
    )
    if s.log_journeys:
        _log(resp, req, s)
    return resp


def _hotspots(segs, readings, mean) -> list[Hotspot]:
    if mean is None:
        return []
    picks = [
        (r.pm25, seg)
        for seg, r in zip(segs, readings)
        if r is not None and r.pm25 is not None and r.pm25 >= mean * 1.2
    ]
    picks.sort(key=lambda x: -x[0])
    out: list[Hotspot] = []
    for pm, seg in picks:
        if any(haversine_m(seg.mid, (h.location.lat, h.location.lng)) < 700 for h in out):
            continue
        out.append(Hotspot(location=_ll(seg.mid), pm25=pm, minutes=round(seg.duration_s / 60, 1)))
        if len(out) == 3:
            break
    return out


def _log(resp: RouteResponse, req: RouteRequest, s: Settings) -> None:
    rec = next(r for r in resp.routes if r.id == resp.recommended_id)
    fast = next(r for r in resp.routes if r.id == resp.fastest_id)
    line = {
        "t": resp.data.computed_at.isoformat(),
        "departure": resp.data.departure_time.isoformat(),
        "provider": resp.data.provider,
        "mode": req.mode.value,
        "preference": req.preference.value,
        "o": [round(req.origin.lat, 3), round(req.origin.lng, 3)],
        "d": [round(req.destination.lat, 3), round(req.destination.lng, 3)],
        "n_candidates": len(resp.routes),
        "n_detours": sum(r.source == "detour" for r in resp.routes),
        "fastest_min": round(fast.duration_s / 60, 1),
        "fastest_exposure": fast.exposure_pm25,
        "rec_min": round(rec.duration_s / 60, 1),
        "rec_exposure": rec.exposure_pm25,
        "reduction_pct": resp.comparison.reduction_pct,
        "meaningful": resp.comparison.meaningful,
        "rec_source": rec.source,
        "usage": resp.usage.model_dump(),
    }
    path = Path(s.journey_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
