"""Google first, open data when Google can't serve the request.

Triggers: quota exceeded (429), key/billing/API-enablement problems (401/403 ->
503), Google outages (5xx), and "no route" for a mode Google doesn't cover.
After an outage or quota error a breaker skips Google for FALLBACK_COOLDOWN_S so
every request isn't slowed by a failing call.

Consistency rules, so one response never mixes data sources in a way that
distorts the comparison:
- Routes: only the main request can fall back. Once it falls back, the detour
  requests for the same trip also use open routing.
- Air quality: all-or-nothing per request (handled in AQService), never a mix
  of Google and open values across segments.
"""

from __future__ import annotations

import logging
import time

from ..models import Usage
from .base import ProviderError

log = logging.getLogger("breatheasy.fallback")

OUTAGE_STATUSES = {429, 502, 503, 504}


class Breaker:
    def __init__(self, cooldown_s: float):
        self.cooldown = cooldown_s
        self.open_until = 0.0

    def ok(self) -> bool:
        return time.monotonic() >= self.open_until

    def record(self, exc: ProviderError) -> None:
        if exc.status in OUTAGE_STATUSES or exc.status >= 500:
            self.open_until = time.monotonic() + self.cooldown


def _note(usage: Usage, what: str, exc: ProviderError | None) -> None:
    usage.fallback = True
    if exc is not None:
        log.warning("google %s failed, using open data: %s (status %s)", what, exc, exc.status)


class FallbackRoutes:
    def __init__(self, primary, secondary, breaker: Breaker):
        self.primary, self.secondary, self.breaker = primary, secondary, breaker

    async def _open(self, origin, destination, mode, alternatives, via, departure_time, usage: Usage):
        scratch = Usage()
        routes = await self.secondary.compute_routes(
            origin, destination, mode, alternatives=alternatives, via=via, departure_time=departure_time, usage=scratch
        )
        usage.open_calls += scratch.routes_calls
        usage.routes_source = "open"
        return routes

    async def compute_routes(self, origin, destination, mode, *, alternatives, via, departure_time, usage: Usage):
        if usage.routes_source == "open":  # this trip already fell back
            return await self._open(origin, destination, mode, alternatives, via, departure_time, usage)
        if via:  # detours stay on the main request's source; failures are skipped upstream
            return await self.primary.compute_routes(
                origin, destination, mode, alternatives=alternatives, via=via, departure_time=departure_time, usage=usage
            )
        exc: ProviderError | None = None
        if self.breaker.ok():
            try:
                routes = await self.primary.compute_routes(
                    origin, destination, mode, alternatives=alternatives, via=via,
                    departure_time=departure_time, usage=usage,
                )
                if routes:
                    usage.routes_source = "google"
                    return routes
            except ProviderError as e:
                exc = e
                self.breaker.record(e)
        _note(usage, "routes", exc)
        return await self._open(origin, destination, mode, alternatives, via, departure_time, usage)


class FallbackAir:
    """Marker wrapper; AQService runs the whole lookup on one source or the other."""

    def __init__(self, primary, secondary, breaker: Breaker):
        self.primary, self.secondary, self.breaker = primary, secondary, breaker


class FallbackPlaces:
    def __init__(self, primary, secondary, breaker: Breaker):
        self.primary, self.secondary, self.breaker = primary, secondary, breaker

    async def autocomplete(self, query, session, bias, usage: Usage):
        if self.breaker.ok():
            try:
                return await self.primary.autocomplete(query, session, bias, usage)
            except ProviderError as e:
                self.breaker.record(e)
                _note(usage, "places", e)
        scratch = Usage()
        out = await self.secondary.autocomplete(query, session, bias, scratch)
        usage.open_calls += scratch.places_autocomplete_calls
        return out

    async def details(self, place_id, session, usage: Usage):
        if place_id.startswith("geo:"):  # id minted by the open geocoder
            return await self.secondary.details(place_id, session, usage)
        return await self.primary.details(place_id, session, usage)
