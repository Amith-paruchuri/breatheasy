"""Daily Google spending cap."""

import asyncio

from app.budget import SpendGuard, google_cost
from app.config import Settings
from app.db import make_engine
from app.migrate import run_migrations
from app.models import LatLng, RouteRequest, TravelMode, Usage
from app.providers import build_providers
from app.services.airquality import AQCache, AQService
from app.services.planner import _CAND_CACHE, plan_routes


def test_cost_uses_india_tiers_per_mode():
    s = Settings(provider="google")
    u = Usage(routes_calls=6, aq_current_calls=30)
    walk = google_cost(u, s, TravelMode.WALK)
    car = google_cost(u, s, TravelMode.DRIVE)
    two = google_cost(u, s, TravelMode.TWO_WHEELER)
    assert round(walk, 4) == round((6 * 1.5 + 30 * 0.5) / 1000, 4)
    assert walk < car < two


def test_guard_records_and_trips_at_the_cap(tmp_path):
    async def run():
        engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/b.db")
        await run_migrations(engine)
        s = Settings(provider="google", google_daily_budget_usd=0.05)
        g = SpendGuard(engine, s)
        assert not await g.over_budget()
        for _ in range(3):
            await g.record(Usage(routes_calls=6, aq_current_calls=30), TravelMode.WALK)
        g._cached = ("", 0.0, 0.0)  # force a fresh read from the database
        assert round(await g.spent_today(), 3) == 0.072
        assert await g.over_budget()
        rows = await g.summary()
        assert rows[0]["searches"] == 3 and rows[0]["aq_calls"] == 90
        await engine.dispose()

    asyncio.run(run())


def test_guard_is_off_for_free_providers(tmp_path):
    s = Settings(provider="open", google_daily_budget_usd=0.01)
    assert not SpendGuard(None, s).enabled


def test_over_budget_search_uses_open_data():
    _CAND_CACHE.clear()
    s = Settings(provider="mock")
    p = build_providers(s)
    req = RouteRequest(origin=LatLng(lat=28.5672, lng=77.21), destination=LatLng(lat=28.6315, lng=77.2167), mode=TravelMode.WALK)
    resp = asyncio.run(plan_routes(req, p, AQService(p.air, s, AQCache(60)), s, None, force_open=True))
    assert resp.routes and any("busy today" in w for w in resp.warnings)
