"""Daily spending cap for Google Maps Platform calls.

Each search adds its estimated Google cost to a per-day row in the database (shared
by every Cloud Run instance). When today's total passes GOOGLE_DAILY_BUDGET_USD, new
searches use free open data until midnight India time, so a traffic spike or abuse
can never run up an unbounded bill.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from .config import Settings
from .models import TravelMode, Usage

log = logging.getLogger("breatheasy.budget")
IST = timezone(timedelta(hours=5, minutes=30))

metadata = sa.MetaData()
api_spend = sa.Table(
    "api_spend",
    metadata,
    sa.Column("day", sa.String(10), primary_key=True),  # YYYY-MM-DD, India time
    sa.Column("searches", sa.Integer, nullable=False, server_default="0"),
    sa.Column("routes_calls", sa.Integer, nullable=False, server_default="0"),
    sa.Column("aq_calls", sa.Integer, nullable=False, server_default="0"),
    sa.Column("places_calls", sa.Integer, nullable=False, server_default="0"),
    sa.Column("est_usd", sa.Float, nullable=False, server_default="0"),
)


def routes_price(mode: TravelMode, s: Settings) -> float:
    if mode == TravelMode.TWO_WHEELER:
        return s.price_routes_enterprise_per_1000_usd
    if mode == TravelMode.DRIVE:
        return s.price_routes_pro_per_1000_usd
    return s.price_routes_per_1000_usd or 0.0


def google_cost(usage: Usage, s: Settings, mode: TravelMode | None = None) -> float:
    """Estimated Google bill for one request's calls (open-data calls are free)."""
    r = routes_price(mode, s) if mode else (s.price_routes_per_1000_usd or 0.0)
    total = (
        usage.routes_calls * r
        + (usage.aq_current_calls + usage.aq_forecast_calls) * (s.price_aq_per_1000_usd or 0.0)
        + usage.places_autocomplete_calls * (s.price_places_autocomplete_per_1000_usd or 0.0)
        + usage.places_details_calls * (s.price_places_details_per_1000_usd or 0.0)
    )
    return total / 1000


def today() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


class SpendGuard:
    def __init__(self, engine: AsyncEngine | None, s: Settings):
        self.engine, self.s = engine, s
        self._cached: tuple[str, float, float] = ("", 0.0, 0.0)  # day, spend, read at

    @property
    def enabled(self) -> bool:
        return self.engine is not None and self.s.provider == "google" and self.s.google_daily_budget_usd > 0

    async def spent_today(self) -> float:
        day = today()
        cday, spend, at = self._cached
        if cday == day and time.monotonic() - at < 30:
            return spend
        try:
            async with self.engine.connect() as c:
                v = await c.scalar(sa.select(api_spend.c.est_usd).where(api_spend.c.day == day))
        except Exception as exc:  # never block searches on bookkeeping
            log.warning("could not read today's spend: %s", exc)
            return spend if cday == day else 0.0
        self._cached = (day, float(v or 0.0), time.monotonic())
        return float(v or 0.0)

    async def over_budget(self) -> bool:
        if not self.enabled:
            return False
        over = await self.spent_today() >= self.s.google_daily_budget_usd
        if over:
            log.warning("daily Google budget of %.2f USD reached; using open data", self.s.google_daily_budget_usd)
        return over

    async def record(self, usage: Usage, mode: TravelMode | None, search: bool = True) -> None:
        if not self.enabled:
            return
        cost = google_cost(usage, self.s, mode)
        aq = usage.aq_current_calls + usage.aq_forecast_calls
        places = usage.places_autocomplete_calls + usage.places_details_calls
        if not (cost or search):
            return
        day = today()
        vals = dict(searches=1 if search else 0, routes_calls=usage.routes_calls, aq_calls=aq, places_calls=places, est_usd=cost)
        try:
            async with self.engine.begin() as c:
                upd = await c.execute(
                    api_spend.update()
                    .where(api_spend.c.day == day)
                    .values({k: getattr(api_spend.c, k) + v for k, v in vals.items()})
                )
                if upd.rowcount == 0:
                    try:
                        async with c.begin_nested():
                            await c.execute(api_spend.insert().values(day=day, **vals))
                    except sa.exc.IntegrityError:  # another instance inserted first
                        await c.execute(
                            api_spend.update()
                            .where(api_spend.c.day == day)
                            .values({k: getattr(api_spend.c, k) + v for k, v in vals.items()})
                        )
        except Exception as exc:
            log.warning("could not record spend: %s", exc)
            return
        cday, spend, at = self._cached
        if cday == day:
            self._cached = (day, spend + cost, at)

    async def summary(self, days: int = 31) -> list[dict]:
        if self.engine is None:
            return []
        async with self.engine.connect() as c:
            rows = (await c.execute(sa.select(api_spend).order_by(api_spend.c.day.desc()).limit(days))).mappings().all()
        return [dict(r) for r in rows]
