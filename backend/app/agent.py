"""Commute agent: natural language to cleaner-air plans."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta

from .config import Settings
from .models import (
    AgentRequest,
    AgentResponse,
    LatLng,
    Preference,
    RouteRequest,
    TravelMode,
    Usage,
)
from .providers import Providers
from .services.airquality import AQService
from .services.planner import IST, plan_routes

log = logging.getLogger("breatheasy.agent")

HEALTH_CONDITIONS = {"asthma", "COPD", "heart", "pregnancy", "elderly", "child"}


def parse_rules(query: str):
    q = query

    # 1. travel mode
    mode = TravelMode.WALK
    m_match = re.search(r"\b(cycle|bicycle|bike|scooter|car|cab|taxi)\b", q, re.I)
    if m_match:
        m = m_match.group(1).lower()
        if m in ("cycle", "bicycle"):
            mode = TravelMode.BICYCLE
        elif m in ("bike", "scooter"):
            mode = TravelMode.TWO_WHEELER
        elif m in ("car", "cab", "taxi"):
            mode = TravelMode.DRIVE
        q = q.replace(m_match.group(0), "")

    # 2. health conditions
    conditions = [c for c in HEALTH_CONDITIONS if re.search(fr"\b{c}\b", q, re.I)]
    for c in conditions:
        q = re.sub(fr"\b{c}\b", "", q, flags=re.I)

    # 3. arrive by time
    arrive_by = None
    t_match = re.search(r"by (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", q, re.I)
    if t_match:
        h = int(t_match.group(1))
        m = int(t_match.group(2)) if t_match.group(2) else 0
        ampm = t_match.group(3).lower() if t_match.group(3) else None
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        now = datetime.now(IST)
        arrive_by = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if arrive_by < now:
            arrive_by += timedelta(days=1)
        q = q.replace(t_match.group(0), "")

    # 4. origin
    origin_query = None
    o_match = re.search(r"\bfrom\s+(.+?)(?=\bto\b|\breach\b|\bat\b|$)", q, re.I)
    if o_match:
        origin_query = o_match.group(1).strip()
        q = q.replace(o_match.group(0), "")

    # 5. destination
    dest_query = None
    d_match = re.search(r"\b(?:reach|to|at)\s+(.+?)$", q.strip(), re.I)
    if d_match:
        dest_query = d_match.group(1).strip()
        # Clean up common leading verbs/junk
        dest_query = re.sub(r"\b(go|want|need|my|a|the|on|to)\b", "", dest_query, flags=re.I).strip()
    elif q.strip():
        dest_query = q.strip()

    return {
        "destination": dest_query,
        "origin": origin_query,
        "arrive_by": arrive_by,
        "mode": mode,
        "conditions": conditions,
    }


async def parse_query(query: str, s: Settings):
    if s.agent_llm == "vertex":
        try:
            # Vertex AI integration would go here. For the prototype, we fall back to rules.
            return parse_rules(query)
        except Exception:
            return parse_rules(query)
    return parse_rules(query)


async def run_agent(
    req: AgentRequest,
    providers: Providers,
    aq: AQService,
    s: Settings,
    env,
    force_open: bool = False,
) -> AgentResponse:
    parsed = await parse_query(req.query, s)
    dest_query = parsed["destination"]
    if not dest_query:
        return AgentResponse(
            verdict="I couldn't figure out where you want to go. Try saying 'I need to reach Hauz Khas by 9 am'."
        )

    usage = Usage()
    bias = (s.region_south, s.region_west, s.region_north, s.region_east)
    suggestions = await providers.places.autocomplete(dest_query, None, bias, usage)
    if not suggestions:
        return AgentResponse(verdict=f"I couldn't find '{dest_query}'. Check the spelling or try a landmark.")

    dest_details = await providers.places.details(suggestions[0].place_id, None, usage)
    dest_ll = dest_details.location

    origin_ll = req.origin
    if parsed["origin"]:
        o_suggestions = await providers.places.autocomplete(parsed["origin"], None, bias, usage)
        if o_suggestions:
            o_details = await providers.places.details(o_suggestions[0].place_id, None, usage)
            origin_ll = o_details.location

    now = datetime.now(IST)
    route_departure = now
    # Use a consistent time budget for all trials to ensure candidate reuse
    agent_max_extra = s.cleanest_air_default_extra_minutes
    base_req = RouteRequest(
        origin=origin_ll,
        destination=dest_ll,
        mode=parsed["mode"],
        preference=Preference.FASTEST,
        max_extra_minutes=agent_max_extra,
    )
    # Get baseline fastest route to estimate duration and for comparison
    base_resp = await plan_routes(base_req, providers, aq, s, env, force_open=force_open, route_departure=route_departure)
    _merge_usage(usage, base_resp.usage)

    if not base_resp.routes:
        return AgentResponse(verdict="I couldn't find any routes. Try a different mode of travel.")

    fastest_duration = base_resp.routes[0].duration_s
    arrive_by = parsed["arrive_by"]

    if arrive_by:
        latest_dep = arrive_by - timedelta(seconds=fastest_duration)
        if latest_dep < now:
            latest_dep = now
        departures = [latest_dep - timedelta(minutes=i * 10) for i in range(4)]
        departures = [d for d in departures if d >= now - timedelta(minutes=5)]
    else:
        departures = [now + timedelta(minutes=i * 15) for i in range(4)]

    # All departure times at once: the routes come from the cache (route_departure),
    # so each call only adds air-quality lookups, and running them together keeps
    # the whole answer within a few seconds of a single search.
    if not departures:
        departures = [now]

    async def one(dep):
        r = RouteRequest(
            origin=origin_ll,
            destination=dest_ll,
            mode=parsed["mode"],
            preference=Preference.CLEANEST,
            departure_time=dep,
            max_extra_minutes=agent_max_extra,
        )
        return dep, await plan_routes(r, providers, aq, s, env, force_open=force_open, route_departure=route_departure)

    plans = list(await asyncio.gather(*(one(d) for d in departures)))
    for _, p in plans:
        _merge_usage(usage, p.usage)

    best_dep, best_route, best_plan = None, None, None
    best_exposure = float("inf")

    # baseline: the fastest route leaving as late as possible (departures[0])
    baseline_dep, baseline_plan = plans[0]
    baseline_route = next(r for r in baseline_plan.routes if r.id == baseline_plan.fastest_id)

    for dep, p in plans:
        for r in p.routes:
            arrival = dep + timedelta(seconds=r.duration_s)
            if arrive_by and arrival > arrive_by + timedelta(minutes=2):
                continue
            if r.exposure_pm25 is not None and r.exposure_pm25 < best_exposure:
                best_exposure = r.exposure_pm25
                best_dep, best_route, best_plan = dep, r, p

    if not best_route:
        best_dep, best_plan = plans[0]
        best_route = next(r for r in best_plan.routes if r.id == best_plan.recommended_id)

    arrival_time = best_dep + timedelta(seconds=best_route.duration_s)
    reduction = ""
    if best_route.exposure_pm25 and baseline_route.exposure_pm25:
        pct = round((baseline_route.exposure_pm25 - best_route.exposure_pm25) / baseline_route.exposure_pm25 * 100)
        if pct > 0:
            reduction = (
                f" That's {pct}% less PM2.5 than the fastest route leaving at "
                f"{baseline_dep.strftime('%H:%M')} (average {round(best_route.mean_pm25)} vs "
                f"{round(baseline_route.mean_pm25)} \u00b5g/m\u00b3)."
            )

    via = f" via {best_route.via}" if best_route.via else ""
    verdict = f"Leave at {best_dep.strftime('%H:%M')}{via}; you'll arrive around {arrival_time.strftime('%H:%M')}.{reduction}"

    if any(c in parsed["conditions"] for c in HEALTH_CONDITIONS) and best_route.mean_pm25 > 200:
        verdict += " Since the air is very poor, please wear an N95 mask and keep your reliever medicine handy."

    best_plan.recommended_id = best_route.id
    best_plan.usage = usage
    return AgentResponse(verdict=verdict, plan=best_plan, mode=parsed["mode"])


def _merge_usage(total: Usage, extra: Usage):
    total.routes_calls += extra.routes_calls
    total.aq_current_calls += extra.aq_current_calls
    total.aq_forecast_calls += extra.aq_forecast_calls
    total.aq_cache_hits += extra.aq_cache_hits
    total.places_autocomplete_calls += extra.places_autocomplete_calls
    total.places_details_calls += extra.places_details_calls
    total.open_calls += extra.open_calls
    total.estimated_cost_usd = (total.estimated_cost_usd or 0) + (extra.estimated_cost_usd or 0)
    total.routes_source = extra.routes_source or total.routes_source
    total.aq_source = extra.aq_source or total.aq_source
