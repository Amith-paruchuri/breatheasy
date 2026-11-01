"""Air-quality lookup with grid de-duplication and a short in-memory cache.

Points are snapped to ~500 m cells (matching the Google AQ resolution) so that
every segment that falls in the same cell, on any candidate route, shares one
lookup. Segments reached in the current hour use current conditions; later
segments use the hourly forecast for the hour they will be reached.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, timedelta, timezone

from ..config import Settings
from ..models import Usage
from ..providers.base import AirQualityProvider, AQReading, ProviderError

Cell = tuple[int, int]
log = logging.getLogger("breatheasy.aq")


def hour_floor(t: datetime) -> datetime:
    return t.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


class AQCache:
    def __init__(self, ttl_s: int):
        self.ttl = ttl_s
        self._d: dict[tuple, tuple[float, AQReading | None]] = {}

    def get(self, key: tuple) -> tuple[bool, AQReading | None]:
        hit = self._d.get(key)
        if hit and hit[0] > time.monotonic():
            return True, hit[1]
        if hit:
            self._d.pop(key, None)
        return False, None

    def put(self, key: tuple, value: AQReading | None) -> None:
        if len(self._d) > 50_000:  # crude bound
            self._d.clear()
        self._d[key] = (time.monotonic() + self.ttl, value)


class AQService:
    def __init__(self, provider: AirQualityProvider, settings: Settings, cache: AQCache):
        self.p = provider
        self.s = settings
        self.cache = cache

    def cell_of(self, lat: float, lng: float, scale: int = 1) -> Cell:
        k = self.s.aq_cell_deg * scale
        return (math.floor(lat / k), math.floor(lng / k))

    def cell_center(self, cell: Cell, scale: int = 1) -> tuple[float, float]:
        k = self.s.aq_cell_deg * scale
        return ((cell[0] + 0.5) * k, (cell[1] + 0.5) * k)

    def choose_scale(self, points: list[tuple[float, float]], min_scale: int = 1) -> int:
        """Smallest grid scale (1, 2, 4, ...) that keeps lookups under MAX_AQ_CELLS.
        Short city trips stay at the native ~500 m grid; very long ones coarsen."""
        scale = max(1, min_scale)
        while scale < 64 and len({self.cell_of(la, ln, scale) for la, ln in points}) > self.s.max_aq_cells:
            scale *= 2
        return scale

    async def lookup(
        self,
        queries: list[tuple[float, float, datetime]],
        now: datetime,
        usage: Usage,
        scale: int = 1,
        force_open: bool = False,
    ) -> list[AQReading | None]:
        """queries: (lat, lng, expected arrival time). Returns readings in the same order.

        With a Google-with-fallback provider the WHOLE lookup runs on one source,
        so a response never compares Google values on one segment with open values
        on another.
        """
        p = self.p
        deadline = self.s.aq_deadline_s
        if not hasattr(p, "secondary"):
            usage.aq_source = self.s.provider
            try:
                return await asyncio.wait_for(self._lookup(p, self.s.provider, queries, now, usage, scale), deadline)
            except asyncio.TimeoutError:
                raise ProviderError(
                    "Checking air quality on this trip took too long. Try again, or pick a closer destination.",
                    504,
                    code="slow",
                ) from None
        if p.breaker.ok() and not force_open:
            try:
                out = await asyncio.wait_for(self._lookup(p.primary, "google", queries, now, usage, scale), deadline)
                usage.aq_source = "google"
                return out
            except asyncio.TimeoutError:
                # Slow, not broken: don't open the breaker, just answer this search from open data.
                log.warning("google air quality exceeded %.0fs for %d points; using open data", deadline, len(queries))
            except ProviderError as exc:
                p.breaker.record(exc)
                log.warning("google air quality failed, using open data: %s (status %s)", exc, exc.status)
        scratch = Usage()
        out = await self._lookup(p.secondary, "open", queries, now, scratch, scale)
        usage.open_calls += scratch.aq_current_calls + scratch.aq_forecast_calls
        usage.aq_cache_hits += scratch.aq_cache_hits
        usage.aq_source = "open"
        usage.fallback = True
        return out

    async def _lookup(
        self, prov, tag: str, queries: list[tuple[float, float, datetime]], now: datetime, usage: Usage, scale: int = 1
    ) -> list[AQReading | None]:
        tag = f"{tag}@{scale}"
        current_until = now + timedelta(minutes=self.s.current_window_min)
        now_hour = hour_floor(now)
        horizon = now_hour + timedelta(hours=self.s.forecast_horizon_h)
        keys: list[tuple] = []
        need_current: set[Cell] = set()
        need_forecast: dict[Cell, set[datetime]] = {}

        for lat, lng, at in queries:
            cell = self.cell_of(lat, lng, scale)
            h = hour_floor(at)
            if h <= now_hour or at <= current_until:
                key = (tag, cell, "current", now_hour)
            elif h <= horizon:
                key = (tag, cell, "forecast", h)
            else:
                key = (tag, cell, "none", h)
            keys.append(key)
            if key[2] == "none":
                continue
            found, _ = self.cache.get(key)
            if found:
                continue
            if key[2] == "current":
                need_current.add(cell)
            else:
                need_forecast.setdefault(cell, set()).add(h)

        sem = asyncio.Semaphore(self.s.max_concurrent_aq_calls)

        async def fetch_current(cell: Cell) -> None:
            async with sem:
                lat, lng = self.cell_center(cell, scale)
                r = await prov.current(lat, lng, usage)
            self.cache.put((tag, cell, "current", now_hour), r)

        async def fetch_forecast(cell: Cell, hours: set[datetime]) -> None:
            async with sem:
                lat, lng = self.cell_center(cell, scale)
                got = await prov.forecast(lat, lng, min(hours), max(hours), usage)
            for h in hours:
                self.cache.put((tag, cell, "forecast", h), got.get(h))

        batch = getattr(prov, "batch_hourly", None)
        if batch is not None and (need_current or need_forecast):
            # Providers that accept many points per request (Open-Meteo) get one
            # batched call covering current conditions and every forecast hour.
            cells = sorted(need_current | set(need_forecast))
            last = max((h for hs in need_forecast.values() for h in hs), default=now_hour)
            days = int((last - now_hour).total_seconds() // 86400) + 2
            results = await batch([self.cell_center(c, scale) for c in cells], days, usage)
            for cell, (current, hourly) in zip(cells, results):
                self.cache.put((tag, cell, "current", now_hour), current or hourly.get(now_hour))
                for h, r in hourly.items():
                    if now_hour < h <= horizon:
                        self.cache.put((tag, cell, "forecast", h), r)
                for h in need_forecast.get(cell, ()):
                    if h not in hourly:
                        self.cache.put((tag, cell, "forecast", h), None)
        else:
            await asyncio.gather(
                *(fetch_current(c) for c in need_current),
                *(fetch_forecast(c, hs) for c, hs in need_forecast.items()),
            )

        out: list[AQReading | None] = []
        counted: set[tuple] = set()
        fetched = {(tag, c, "current", now_hour) for c in need_current} | {
            (tag, c, "forecast", h) for c, hs in need_forecast.items() for h in hs
        }
        for key in keys:
            if key[2] == "none":
                out.append(None)
                continue
            _, r = self.cache.get(key)
            if key not in fetched and key not in counted:
                usage.aq_cache_hits += 1
                counted.add(key)
            out.append(r)
        return out
