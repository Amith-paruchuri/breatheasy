"""Fallback behaviour, security headers, SPA serving and production config checks."""

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.models import Usage, TravelMode
from app.providers.base import AQReading, ProviderError, RawRoute
from app.providers.fallback import Breaker, FallbackAir, FallbackPlaces, FallbackRoutes
from app.services.airquality import AQCache, AQService


class FakeRoutes:
    def __init__(self, tag, fail=None, empty=False):
        self.tag, self.fail, self.empty, self.calls = tag, fail, empty, 0

    async def compute_routes(self, o, d, mode, *, alternatives, via, departure_time, usage):
        self.calls += 1
        usage.routes_calls += 1
        if self.fail:
            raise ProviderError("boom", self.fail)
        if self.empty:
            return []
        return [RawRoute(points=[o, d], encoded_polyline="x", distance_m=1, duration_s=1, labels=[self.tag])]


@pytest.mark.parametrize("status", [429, 503, 502])
def test_routes_fall_back_and_breaker_opens(status):
    g, o = FakeRoutes("google", fail=status), FakeRoutes("open")
    fr = FallbackRoutes(g, o, Breaker(60))
    u = Usage()
    r = asyncio.run(fr.compute_routes((0, 0), (1, 1), TravelMode.WALK, alternatives=True, via=None, departure_time=None, usage=u))
    assert r[0].labels == ["open"] and u.routes_source == "open" and u.fallback and u.open_calls == 1
    # detour for the same trip stays on open data
    asyncio.run(fr.compute_routes((0, 0), (1, 1), TravelMode.WALK, alternatives=False, via=[(0.5, 0.5)], departure_time=None, usage=u))
    assert g.calls == 1 and o.calls == 2
    # next request skips Google entirely while the breaker is open
    u2 = Usage()
    asyncio.run(fr.compute_routes((0, 0), (1, 1), TravelMode.WALK, alternatives=True, via=None, departure_time=None, usage=u2))
    assert g.calls == 1 and u2.routes_source == "open"


def test_no_google_route_falls_back_without_tripping_breaker():
    g, o = FakeRoutes("google", empty=True), FakeRoutes("open")
    br = Breaker(60)
    fr = FallbackRoutes(g, o, br)
    u = Usage()
    asyncio.run(fr.compute_routes((0, 0), (1, 1), TravelMode.BICYCLE, alternatives=True, via=None, departure_time=None, usage=u))
    assert u.routes_source == "open" and br.ok()


def test_healthy_google_is_used():
    g, o = FakeRoutes("google"), FakeRoutes("open")
    u = Usage()
    asyncio.run(FallbackRoutes(g, o, Breaker(60)).compute_routes((0, 0), (1, 1), TravelMode.DRIVE, alternatives=True, via=None, departure_time=None, usage=u))
    assert u.routes_source == "google" and not u.fallback and o.calls == 0


class FakeAQ:
    def __init__(self, value, fail=None):
        self.value, self.fail, self.calls = value, fail, 0

    async def current(self, lat, lng, usage):
        self.calls += 1
        usage.aq_current_calls += 1
        if self.fail:
            raise ProviderError("quota", self.fail)
        return AQReading(self.value, None, None, None, datetime.now(timezone.utc), "current")

    async def forecast(self, lat, lng, start, end, usage):
        return {}


def test_air_quality_is_all_or_nothing():
    g, o = FakeAQ(50.0, fail=429), FakeAQ(120.0)
    svc = AQService(FallbackAir(g, o, Breaker(60)), Settings(provider="google"), AQCache(600))
    now = datetime.now(timezone.utc)
    u = Usage()
    out = asyncio.run(svc.lookup([(28.5, 77.2, now), (28.6, 77.3, now)], now, u))
    assert [r.pm25 for r in out] == [120.0, 120.0]  # never a mix of 50 and 120
    assert u.aq_source == "open" and u.fallback and u.open_calls == 2 and u.aq_current_calls == 2  # two failed Google attempts


def test_places_fallback_and_id_routing():
    class P:
        def __init__(self, tag, fail=None):
            self.tag, self.fail = tag, fail

        async def autocomplete(self, q, session, bias, usage):
            if self.fail:
                raise ProviderError("x", self.fail)
            return [self.tag]

        async def details(self, pid, session, usage):
            return self.tag

    fp = FallbackPlaces(P("google", fail=503), P("open"), Breaker(60))
    assert asyncio.run(fp.autocomplete("a", None, (0, 0, 1, 1), Usage())) == ["open"]
    assert asyncio.run(fp.details("geo:1,2:x", None, Usage())) == "open"
    assert asyncio.run(fp.details("ChIJabc", None, Usage())) == "google"


def test_security_headers_and_csrf():
    from app.main import app

    with TestClient(app) as c:
        r = c.get("/api/health")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert "content-security-policy-report-only" in r.headers
        assert "accounts.google.com/gsi/client" in r.headers["content-security-policy-report-only"]
        assert r.headers["cross-origin-opener-policy"] == "same-origin-allow-popups"
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["x-request-id"]
        assert c.post("/api/routes", json={}).status_code == 403  # no CSRF header
        cfg = c.get("/api/config").json()
        assert cfg["accounts_enabled"] is True and "maps_browser_key" in cfg


def test_production_config_refuses_unsafe_settings():
    bad = Settings(env="production", provider="google", session_secret="short", database_url="sqlite+aiosqlite:///x.db")
    problems = " ".join(bad.production_problems())
    for needle in ("SESSION_SECRET", "SQLite", "GOOGLE_MAPS_SERVER_KEY", "GOOGLE_MAPS_BROWSER_KEY"):
        assert needle in problems
    good = Settings(
        env="production", provider="google", session_secret="s" * 40,
        database_url="postgresql+asyncpg://u:p@/db?host=/cloudsql/p:r:i",
        google_maps_server_key="k", google_maps_browser_key="b",
    )
    assert good.production_problems() == []


def test_spa_serving(tmp_path):
    from fastapi import FastAPI
    from app.web import mount_frontend

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets" / "app-123.js").write_text("console.log(1)")
    (tmp_path / "sw.js").write_text("//sw")
    a = FastAPI()
    assert mount_frontend(a, str(tmp_path))
    with TestClient(a) as c:
        assert c.get("/").text == "<html>app</html>"
        assert c.get("/account").text == "<html>app</html>"  # client-side route
        r = c.get("/assets/app-123.js")
        assert "immutable" in r.headers["cache-control"]
        assert c.get("/sw.js").headers["cache-control"] == "no-cache"
        assert c.get("/assets/missing.js").status_code == 404
        assert c.get("/api/nope").status_code == 404
        assert c.get("/../../etc/passwd").status_code in (200, 404)  # never escapes root
        assert "root:" not in c.get("/..%2F..%2Fetc%2Fpasswd").text


def test_logs_never_contain_query_strings(caplog):
    import logging

    from app.main import app

    with caplog.at_level(logging.DEBUG):
        with TestClient(app) as c:
            c.get("/api/places/autocomplete", params={"q": "secret home address"})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "secret" not in text and "home address" not in text
    assert logging.getLogger("httpx").level >= logging.WARNING
