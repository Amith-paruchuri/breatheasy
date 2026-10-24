"""Every search must stay small and fast, whatever the user types."""

import asyncio
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.models import Usage
from app.providers.base import AQReading, ProviderError
from app.providers.fallback import Breaker, FallbackAir
from app.services.airquality import AQCache, AQService

FAR_O = {"lat": 28.275, "lng": 77.448}  # ~40 km from AIIMS
AIIMS = {"lat": 28.5663, "lng": 77.2085}


@pytest.fixture(scope="module")
def client():
    with TestClient(app, headers={"X-Requested-With": "breatheasy"}) as c:
        yield c


def test_too_far_to_walk_is_explained_with_alternatives(client):
    r = client.post("/api/routes", json={"origin": FAR_O, "destination": AIIMS, "mode": "WALK"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "too_far"
    assert "DRIVE" in body["suggest_modes"] and "WALK" not in body["suggest_modes"]
    assert "km apart" in body["detail"]


def test_long_drive_is_bounded(client):
    r = client.post("/api/routes", json={"origin": FAR_O, "destination": AIIMS, "mode": "DRIVE"})
    assert r.status_code == 200
    b = r.json()
    for route in b["routes"]:
        assert len(route["segments"]) <= 41
    assert b["usage"]["aq_current_calls"] + b["usage"]["aq_forecast_calls"] <= 90
    assert b["usage"]["routes_calls"] == 1  # no detours on long trips


def test_grid_coarsens_to_cap_lookups():
    s = Settings(provider="mock", max_aq_cells=20)
    svc = AQService(None, s, AQCache(1))
    pts = [(28.2 + i * 0.01, 77.2 + i * 0.01) for i in range(100)]
    scale = svc.choose_scale(pts)
    assert scale > 1 and len({svc.cell_of(a, b, scale) for a, b in pts}) <= 20
    assert svc.choose_scale(pts[:5]) == 1  # short trips keep the native grid


class SlowAQ:
    async def current(self, lat, lng, usage):
        usage.aq_current_calls += 1
        await asyncio.sleep(5)
        return AQReading(50.0, None, None, None, datetime.now(timezone.utc), "current")

    async def forecast(self, *a, **k):
        return {}


class FastAQ(SlowAQ):
    async def current(self, lat, lng, usage):
        usage.aq_current_calls += 1
        return AQReading(99.0, None, None, None, datetime.now(timezone.utc), "current")


def test_slow_google_air_quality_falls_back_within_deadline():
    breaker = Breaker(60)
    s = Settings(provider="google", aq_deadline_s=0.3)
    svc = AQService(FallbackAir(SlowAQ(), FastAQ(), breaker), s, AQCache(60))
    now = datetime.now(timezone.utc)
    u = Usage()
    t = time.perf_counter()
    out = asyncio.run(svc.lookup([(28.5, 77.2, now), (28.6, 77.3, now)], now, u))
    assert time.perf_counter() - t < 2
    assert [r.pm25 for r in out] == [99.0, 99.0] and u.aq_source == "open" and u.fallback
    assert breaker.ok()  # slowness alone doesn't take Google out of service


def test_slow_air_quality_without_fallback_is_a_clear_error():
    s = Settings(provider="mock", aq_deadline_s=0.2)
    svc = AQService(SlowAQ(), s, AQCache(60))
    now = datetime.now(timezone.utc)
    with pytest.raises(ProviderError) as e:
        asyncio.run(svc.lookup([(28.5, 77.2, now)], now, Usage()))
    assert e.value.code == "slow" and e.value.status == 504


def test_first_hour_uses_current_conditions():
    calls = {"current": 0, "forecast": 0}

    class Count:
        async def current(self, lat, lng, usage):
            calls["current"] += 1
            return AQReading(10.0, None, None, None, datetime.now(timezone.utc), "current")

        async def forecast(self, lat, lng, start, end, usage):
            calls["forecast"] += 1
            return {}

    svc = AQService(Count(), Settings(provider="mock"), AQCache(60))
    now = datetime(2026, 10, 22, 14, 59, tzinfo=timezone.utc)
    from datetime import timedelta

    asyncio.run(svc.lookup([(28.5, 77.2, now + timedelta(minutes=20))], now, Usage()))
    assert calls == {"current": 1, "forecast": 0}  # 15:19 is next hour but within the first hour of the trip
