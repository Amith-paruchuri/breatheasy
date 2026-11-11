"""Indian AQI, street-level context from OpenStreetMap, cleanest-air ranking and green corridors."""

import asyncio
import gzip
import json
import sys
from pathlib import Path

import pytest

from app.aqi import compute_aqi, ppb_to_ugm3, sub_index
from app.config import Settings
from app.environment import EnvironmentLayer, highlights
from app.models import LatLng, Preference, RouteRequest, TravelMode
from app.providers import build_providers
from app.services.airquality import AQCache, AQService
from app.services.planner import _CAND_CACHE, plan_routes
from app.services.ranking import Scored, pick

AIIMS = (28.5672, 77.2100)
CP = (28.6315, 77.2167)


# ---------------- AQI ----------------
@pytest.mark.parametrize(
    "conc,expected",
    [(0, 0), (30, 50), (60, 100), (61, 101), (90, 200), (120, 300), (250, 400), (380, 500), (900, 500)],
)
def test_pm25_sub_index_matches_cpcb_breakpoints(conc, expected):
    assert round(sub_index("pm25", conc)) == expected


def test_aqi_is_the_worst_pollutant():
    r = compute_aqi(pm25=45, pm10=300)  # PM2.5 ~75, PM10 = 250
    assert r.aqi == 250 and r.dominant == "pm10" and r.category == "Poor"
    assert compute_aqi(no2=50) is None  # no particulate value, no AQI
    assert round(ppb_to_ugm3("no2", 100)) == 188


# ---------------- environment layer ----------------
def square(lat, lng, half_deg):
    return [[lat - half_deg, lng - half_deg], [lat - half_deg, lng + half_deg], [lat + half_deg, lng + half_deg],
            [lat + half_deg, lng - half_deg], [lat - half_deg, lng - half_deg]]


@pytest.fixture()
def env(tmp_path):
    data = {
        "source": "test",
        "areas": [
            {"kind": "green", "name": "Test Garden", "area_m2": 360000, "rings": [square(28.600, 77.236, 0.003)]},
            {"kind": "water", "name": "Test Lake", "area_m2": 40000, "rings": [square(28.640, 77.300, 0.001)]},
            {"kind": "industrial", "name": "Test Industrial Area", "area_m2": 90000, "rings": [square(28.58, 77.30, 0.002)]},
        ],
        # a busy road straight along the direct AIIMS -> CP line
        "roads": [{"name": "Test Ring Road", "cls": "trunk", "pts": [list(AIIMS), list(CP)]}],
    }
    p = tmp_path / "env.json.gz"
    with gzip.open(p, "wt") as f:
        json.dump(data, f)
    return EnvironmentLayer.load(p)


def test_point_queries(env):
    areas, roads = env.near((28.600, 77.236))  # middle of the park
    assert [a.name for a in areas] == ["Test Garden"] and roads == []
    areas, roads = env.near((28.600, 77.2405))  # ~120 m east of the park edge: too far
    assert areas == []
    mid = ((AIIMS[0] + CP[0]) / 2, (AIIMS[1] + CP[1]) / 2)
    _, roads = env.near(mid)
    assert roads and roads[0].name == "Test Ring Road"


def test_missing_layer_is_harmless(tmp_path):
    e = EnvironmentLayer.load(tmp_path / "nope.json.gz")
    assert e.empty


def test_green_waypoints_find_the_park_off_the_direct_route(env):
    picks = env.green_waypoints(AIIMS, CP, max_extra_m=3000, avoid=[AIIMS, CP])
    assert picks and picks[0][1] == "Test Garden"
    assert env.green_waypoints(AIIMS, CP, max_extra_m=100, avoid=[AIIMS, CP]) == []  # no time to spare


def test_highlights_text():
    from app.environment import RouteContext

    rc = RouteContext(minutes_green=12, minutes_busy_road=7, total_minutes=60,
                      green_by_name={"Lodhi Garden": 8, "Sunder Nursery": 4}, roads_by_name={"Lodhi Road": 7})
    h = highlights(rc, "WALK")
    assert h[0]["kind"] == "green" and "Lodhi Garden and Sunder Nursery" in h[0]["text"]
    assert any(x["kind"] == "road" and "Lodhi Road" in x["text"] for x in h)
    quiet = highlights(RouteContext(total_minutes=30), "WALK")
    assert quiet == [{"kind": "quiet", "text": "Keeps off busy main roads"}]


# ---------------- ranking ----------------
def test_cleanest_air_takes_a_much_longer_route_when_air_is_clearly_better():
    fast = Scored("fast", 1800, 3000.0, set(), mean_aqi=260, mean_pm25=110)
    green = Scored("green", 1800 + 30 * 60, 3900.0, set(), mean_aqi=180, mean_pm25=85)  # +30 min, more total dose
    near = Scored("near", 1900, 2950.0, set(), mean_aqi=255, mean_pm25=108)
    rec, f, c = pick([fast, green, near], Preference.CLEANEST_AIR, 45, 1.5, 10, 5)
    assert (rec, f) == ("green", "fast") and c["basis"] == "pm25" and c["meaningful"]
    assert c["recommended_pm25"] == 85 and c["fastest_pm25"] == 110 and "85" in c["message"]
    assert c["recommended_aqi"] == 180 and c["fastest_aqi"] == 260  # AQI still reported
    # outside the time budget it is not chosen
    rec, _, _ = pick([fast, green, near], Preference.CLEANEST_AIR, 20, 1.5, 10, 5)
    assert rec == "fast"


def test_cleanest_air_ignores_tiny_differences():
    fast = Scored("fast", 1800, 3000.0, set(), mean_aqi=200, mean_pm25=80)
    other = Scored("other", 2400, 2900.0, set(), mean_aqi=195, mean_pm25=77)
    rec, _, c = pick([fast, other], Preference.CLEANEST_AIR, 45, 1.5, 10, 5)
    assert rec == "fast" and not c["meaningful"] and "about the same" in c["message"]


# ---------------- end to end on mock data ----------------
def test_plan_has_aqi_highlights_and_a_green_corridor(env):
    _CAND_CACHE.clear()
    s = Settings(provider="mock")
    p = build_providers(s)
    aq = AQService(p.air, s, AQCache(60))
    req = RouteRequest(origin=LatLng(lat=AIIMS[0], lng=AIIMS[1]), destination=LatLng(lat=CP[0], lng=CP[1]),
                       mode=TravelMode.WALK, preference=Preference.CLEANEST_AIR)
    resp = asyncio.run(plan_routes(req, p, aq, s, env))
    assert resp.preference == Preference.CLEANEST_AIR and resp.max_extra_minutes == s.cleanest_air_default_extra_minutes
    assert resp.comparison.basis == "pm25"
    sources = {r.source for r in resp.routes}
    assert "green" in sources
    green = next(r for r in resp.routes if r.source == "green")
    assert any("Test Garden" in h.text for h in green.highlights)
    assert green.minutes_green > 0
    for r in resp.routes:
        assert r.mean_aqi is not None and r.aqi_category and r.peak_aqi >= r.mean_aqi
        assert all(seg.aqi is not None for seg in r.segments)
    # cards are ordered: recommended, then by average AQI
    rest = [r.mean_aqi for r in resp.routes[1:]]
    assert rest == sorted(rest)
    assert "CPCB" in resp.data.resolution_note and "OpenStreetMap" in resp.data.resolution_note


def test_street_adjustment_raises_busy_road_and_lowers_green(env):
    _CAND_CACHE.clear()
    s = Settings(provider="mock")
    p = build_providers(s)
    req = RouteRequest(origin=LatLng(lat=AIIMS[0], lng=AIIMS[1]), destination=LatLng(lat=CP[0], lng=CP[1]),
                       mode=TravelMode.WALK, explore_detours=False)
    plain = asyncio.run(plan_routes(req, p, AQService(p.air, s, AQCache(60)), s, None))
    _CAND_CACHE.clear()
    adj = asyncio.run(plan_routes(req, p, AQService(p.air, s, AQCache(60)), s, env))
    by_id = {r.id: r for r in plain.routes}
    # the route running along "Test Ring Road" gets a higher estimate with street context
    road_route = max(adj.routes, key=lambda r: r.minutes_busy_road)
    assert road_route.minutes_busy_road > 0
    assert road_route.mean_pm25 > by_id[road_route.id].mean_pm25


# ---------------- OSM build script helpers ----------------
def test_build_script_helpers():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import build_environment as b

    xy = b.proj(28.6)
    ring = [(28.0, 77.0), (28.0, 77.001), (28.001, 77.001), (28.001, 77.0), (28.0, 77.0)]
    assert 10_000 < b.ring_area(ring, xy) < 12_000  # ~110 m x 98 m
    pieces = [[(0, 0), (0, 1)], [(1, 1), (0, 1)], [(1, 1), (1, 0), (0, 0)]]
    rings = b.stitch(pieces)
    assert len(rings) == 1 and rings[0][0] == rings[0][-1]
    line = [(28.0, 77.0 + i * 0.0001) for i in range(50)]
    assert len(b.simplify(line, 5, xy)) == 2
    assert b.kind_of({"leisure": "park"}) == "green" and b.kind_of({"natural": "water"}) == "water"
    assert b.kind_of({"landuse": "construction"}) == "construction" and b.kind_of({"shop": "x"}) is None
    assert b.name_of({"name": "लोधी गार्डन", "name:en": "Lodhi Garden"}) == "Lodhi Garden"


def test_build_script_end_to_end_with_fake_overpass(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import build_environment as b

    park = [{"lat": 28.590, "lon": 77.215}, {"lat": 28.590, "lon": 77.222}, {"lat": 28.596, "lon": 77.222},
            {"lat": 28.596, "lon": 77.215}, {"lat": 28.590, "lon": 77.215}]
    lake_a = [{"lat": 28.60, "lon": 77.24}, {"lat": 28.60, "lon": 77.245}, {"lat": 28.603, "lon": 77.245}]
    lake_b = [{"lat": 28.603, "lon": 77.245}, {"lat": 28.603, "lon": 77.24}, {"lat": 28.60, "lon": 77.24}]
    tiny = [{"lat": 28.61, "lon": 77.20}, {"lat": 28.61, "lon": 77.2001}, {"lat": 28.6101, "lon": 77.2001},
            {"lat": 28.61, "lon": 77.20}]
    areas = {"elements": [
        {"type": "way", "id": 1, "tags": {"leisure": "park", "name": "Lodhi Garden"}, "geometry": park},
        {"type": "relation", "id": 2, "tags": {"natural": "water", "name": "Test Lake"},
         "members": [{"type": "way", "role": "outer", "geometry": lake_a},
                     {"type": "way", "role": "outer", "geometry": lake_b}]},
        {"type": "way", "id": 3, "tags": {"leisure": "park"}, "geometry": tiny},  # too small, dropped
    ]}
    roads = {"elements": [{"type": "way", "id": 9, "tags": {"highway": "trunk", "name": "Ring Road"},
                           "geometry": [{"lat": 28.58, "lon": 77.21}, {"lat": 28.62, "lon": 77.21}]}]}
    calls = []

    def fake_fetch(query, ua):
        calls.append(query)
        return roads if "highway" in query else areas

    monkeypatch.setattr(b, "fetch", fake_fetch)
    monkeypatch.setattr(b.time, "sleep", lambda s: None)
    out = tmp_path / "env.json.gz"
    monkeypatch.setattr(sys, "argv", ["x", "--tiles", "1", "--cities", "Delhi-NCR", "--out", str(out)])
    b.main()
    env = EnvironmentLayer.load(out).at((28.6, 77.2))
    names = sorted(a.name for a in env.areas)
    assert names == ["Lodhi Garden", "Test Lake"] and len(env.roads) == 1
    assert env.near((28.593, 77.218))[0][0].name == "Lodhi Garden"
    assert len(calls) == 2 and "Breatheasy" not in calls[0]  # contact goes in the User-Agent, not the query


def test_simplify_keeps_closed_rings():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import build_environment as b

    xy = b.proj(28.6)
    ring = [(28.59, 77.215), (28.59, 77.222), (28.596, 77.222), (28.596, 77.215), (28.59, 77.215)]
    out = b.simplify(ring, 10.0, xy)
    assert len(out) == 5 and out[0] == out[-1]
