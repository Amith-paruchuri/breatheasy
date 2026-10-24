"""Open-data provider against a fake upstream that mimics the documented response formats
of OSRM (routing.openstreetmap.de), Open-Meteo Air Quality and Photon."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.geo import encode_polyline
from app.models import RouteRequest, TravelMode, Usage, LatLng
from app.providers import Providers
from app.providers.open import OpenAirQuality, OpenPlaces, OpenRoutes, decode_place_id
from app.services.airquality import AQCache, AQService
from app.services.planner import plan_routes


def _osrm_route(a, b, bend, speed):
    mid = ((a[0] + b[0]) / 2 + bend, (a[1] + b[1]) / 2 - bend)
    pts = [a, ((a[0] + mid[0]) / 2, (a[1] + mid[1]) / 2), mid, ((mid[0] + b[0]) / 2, (mid[1] + b[1]) / 2), b]
    dist = 6000 + abs(bend) * 40000
    steps = [
        {"geometry": encode_polyline(pts[:3]), "distance": dist / 2, "duration": dist / 2 / speed, "name": "x"},
        {"geometry": encode_polyline(pts[2:]), "distance": dist / 2, "duration": dist / 2 / speed, "name": "y"},
        {"geometry": encode_polyline([b, b]), "distance": 0, "duration": 0, "name": ""},  # arrive step
    ]
    return {"geometry": encode_polyline(pts), "distance": dist, "duration": dist / speed, "weight": 1,
            "legs": [{"steps": steps, "distance": dist, "duration": dist / speed, "summary": ""}]}


def fake_upstream(calls):
    def handler(req: httpx.Request):
        calls.append(req)
        host, path, q = req.url.host, req.url.path, dict(req.url.params)
        if host == "routing.openstreetmap.de":
            coords = path.split("/driving/")[1].split(";")
            pts = [(float(c.split(",")[1]), float(c.split(",")[0])) for c in coords]
            if abs(pts[0][0] - pts[-1][0]) < 1e-6 and abs(pts[0][1] - pts[-1][1]) < 1e-6:
                return httpx.Response(400, json={"code": "NoRoute", "message": "Impossible route"})
            speed = 1.4 if "foot" in path else 8.0
            if len(pts) > 2:
                return httpx.Response(200, json={"code": "Ok", "routes": [_osrm_route(pts[0], pts[-1], 0.01, speed)], "waypoints": []})
            routes = [_osrm_route(pts[0], pts[-1], 0.0, speed)]
            if q.get("alternatives") not in (None, "false"):
                routes.append(_osrm_route(pts[0], pts[-1], -0.006, speed))
            return httpx.Response(200, json={"code": "Ok", "routes": routes, "waypoints": []})
        if host == "air-quality-api.open-meteo.com":
            lats = [float(x) for x in q["latitude"].split(",")]
            now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            out = []
            for lat in lats:
                base = 100 + (lat - 28.5) * 400  # varies with latitude so routes differ
                times = [(now + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(-2, 48)]
                out.append({
                    "latitude": lat, "longitude": 77.2, "generationtime_ms": 0.1, "utc_offset_seconds": 0,
                    "timezone": "GMT", "timezone_abbreviation": "GMT", "elevation": 216.0,
                    "current_units": {"time": "iso8601", "interval": "seconds", "pm2_5": "μg/m³"},
                    "current": {"time": now.strftime("%Y-%m-%dT%H:%M"), "interval": 3600, "pm2_5": round(base, 1),
                                "pm10": round(base * 1.6, 1), "nitrogen_dioxide": 40.0, "european_aqi": 90},
                    "hourly_units": {"time": "iso8601", "pm2_5": "μg/m³"},
                    "hourly": {"time": times, "pm2_5": [round(base + i, 1) for i in range(len(times))],
                               "pm10": [None] * len(times), "nitrogen_dioxide": [30.0] * len(times)},
                })
            return httpx.Response(200, json=out if len(out) > 1 else out[0])
        if host == "photon.komoot.io":
            return httpx.Response(200, json={"type": "FeatureCollection", "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [77.2100, 28.5672]},
                 "properties": {"osm_id": 1, "name": "All India Institute of Medical Sciences", "district": "Ansari Nagar",
                                "city": "New Delhi", "state": "Delhi", "country": "India"}},
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [77.21, 28.56]},
                 "properties": {"osm_id": 2, "street": "Aurobindo Marg", "city": "New Delhi", "state": "Delhi"}},
            ]})
        return httpx.Response(404)
    return handler


def make_providers(calls):
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake_upstream(calls)))
    return Providers(
        OpenRoutes(http, "https://routing.openstreetmap.de"),
        OpenAirQuality(http, "https://air-quality-api.open-meteo.com/v1/air-quality"),
        OpenPlaces(http, "https://photon.komoot.io/api/"),
        "open", http, free=True,
    )


@pytest.mark.asyncio
async def test_osrm_profiles_and_parsing():
    calls = []
    p = make_providers(calls)
    u = Usage()
    walk = await p.routes.compute_routes((28.5672, 77.21), (28.6315, 77.2167), TravelMode.WALK,
                                         alternatives=True, via=None, departure_time=None, usage=u)
    assert len(walk) == 2 and len(walk[0].steps) == 3
    assert "/routed-foot/route/v1/driving/77.210000,28.567200;77.216700,28.631500" in str(calls[-1].url)
    car = await p.routes.compute_routes((28.5672, 77.21), (28.6315, 77.2167), TravelMode.TWO_WHEELER,
                                        alternatives=False, via=[(28.6, 77.25)], departure_time=None, usage=u)
    assert "/routed-car/" in str(calls[-1].url) and calls[-1].url.params["alternatives"] == "false"
    assert car[0].duration_s == pytest.approx(car[0].distance_m / 8.0 * 1.35)  # traffic factor
    with pytest.raises(Exception, match="No route"):
        await p.routes.compute_routes((28.5, 77.2), (28.5, 77.2), TravelMode.WALK, alternatives=True,
                                      via=None, departure_time=None, usage=u)


@pytest.mark.asyncio
async def test_open_meteo_batch_one_call_for_many_cells():
    calls = []
    p = make_providers(calls)
    svc = AQService(p.air, Settings(provider="open"), AQCache(600))
    now = datetime.now(timezone.utc)
    q = [(28.55 + i * 0.01, 77.21, now + timedelta(minutes=10 * i)) for i in range(20)]  # 20 cells, ~3 h
    u = Usage()
    out = await svc.lookup(q, now, u)
    assert len(calls) == 1 and u.aq_current_calls == 1
    assert all(r is not None and r.pm25 > 0 for r in out)
    assert out[0].kind == "current" and out[-1].kind == "forecast"


@pytest.mark.asyncio
async def test_photon_places_roundtrip():
    calls = []
    p = make_providers(calls)
    s = await p.places.autocomplete("aiims", None, (28.2, 76.8, 28.95, 77.75), Usage())
    assert s[0].primary.startswith("All India") and "New Delhi" in s[0].secondary
    assert calls[-1].url.params["bbox"] == "76.8,28.2,77.75,28.95"
    d = await p.places.details(s[0].place_id, None, Usage())
    assert d.location.lat == pytest.approx(28.5672) and d.name.startswith("All India")
    assert decode_place_id(s[1].place_id).name == "Aurobindo Marg"


@pytest.mark.asyncio
async def test_full_plan_on_open_provider():
    calls = []
    p = make_providers(calls)
    s = Settings(provider="open")
    aq = AQService(p.air, s, AQCache(600))
    for mode in TravelMode:
        req = RouteRequest(origin=LatLng(lat=28.5672, lng=77.21), destination=LatLng(lat=28.6315, lng=77.2167), mode=mode)
        resp = await plan_routes(req, p, aq, s)
        assert len(resp.routes) >= 3
        assert all(r.coverage == 1.0 and r.exposure_pm25 for r in resp.routes)
        assert resp.usage.estimated_cost_usd == 0.0
        assert "CAMS" in resp.data.resolution_note
    await p.aclose()


def test_api_place_id_with_special_chars_survives_url(monkeypatch):
    from app import main

    calls = []
    with TestClient(main.app) as c:
        main.app.state.providers = make_providers(calls)
        sug = c.get("/api/places/autocomplete", params={"q": "aiims"}).json()
        from urllib.parse import quote
        d = c.get("/api/places/" + quote(sug[0]["place_id"], safe="")).json()
        assert d["location"]["lat"] == pytest.approx(28.5672)
