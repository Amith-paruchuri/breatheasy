"""Validation statistics, station fetching and anonymous usage counts."""

import asyncio
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_accounts import H

from app import validation as v


def _row(run, city, station, s, g, a=None, road=False, green=False):
    return {"run_at": run, "city": city, "state": "", "station": station, "station_pm25": s, "google_pm25": g,
            "adjusted_pm25": g if a is None else a, "near_road": road, "near_green": green, "street_layer": True}


def test_summary_numbers():
    t = datetime(2026, 11, 12, tzinfo=timezone.utc)
    rows = [_row(t, "Delhi", "A", 200, 180), _row(t, "Delhi", "B", 150, 140), _row(t, "Delhi", "C", 100, 120),
            _row(t, "Mumbai", "D", 60, 70)]
    s = v.summarize(rows)
    assert s["samples"] == 4 and s["stations"] == 4
    assert s["google"]["mae"] == round((20 + 10 + 20 + 10) / 4, 1)
    # Delhi: A>B>C officially, model keeps the same order -> all 3 pairs agree
    assert s["order_google"] == {"pairs": 3, "agree_pct": 100.0}
    assert "Delhi" in s["cities"] and s["cities"]["Delhi"]["stations"] == 3


def test_order_ignores_small_gaps_and_other_cities():
    t = datetime(2026, 11, 12, tzinfo=timezone.utc)
    rows = [_row(t, "Delhi", "A", 100, 90), _row(t, "Delhi", "B", 95, 99), _row(t, "Mumbai", "C", 40, 300)]
    assert v._order_agreement(rows, "google_pm25") == {"pairs": 0, "agree_pct": None}


def test_city_grouping_and_city_of():
    assert v.city_group("Gurugram", "Haryana") == "Delhi"
    assert v.city_group("Bangalore") == "Bengaluru"
    assert v.city_of(28.6, 77.2) == "Delhi-NCR" and v.city_of(26.9, 75.8) == "Rest of India"
    assert v.city_of(51.5, -0.1) == "Outside India" and v.city_of(None, None) == "Unknown"


def test_fetch_stations_parses_both_field_names():
    def handler(req):
        assert req.url.params["filters[pollutant_id]"] == "PM2.5"
        return httpx.Response(200, json={"records": [
            {"station": "ITO, Delhi - CPCB", "city": "Delhi", "state": "Delhi", "latitude": "28.628", "longitude": "77.241",
             "pollutant_id": "PM2.5", "avg_value": "212", "last_update": "12-11-2026 11:00:00"},
            {"station": "Old", "city": "Mumbai", "state": "Maharashtra", "latitude": "19.07", "longitude": "72.87",
             "pollutant_id": "PM2.5", "pollutant_avg": "NA"},
            {"station": "Bandra", "city": "Mumbai", "state": "Maharashtra", "latitude": "19.06", "longitude": "72.84",
             "pollutant_id": "PM2.5", "pollutant_avg": "48"},
        ]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await v.fetch_stations(http, "k")

    st = asyncio.run(go())
    assert [(x["station"], x["pm25"]) for x in st] == [("ITO, Delhi - CPCB", 212.0), ("Bandra", 48.0)]


@pytest.fixture()
def client():
    with TestClient(app, headers=H) as c:
        yield c


def test_events_stats_and_run_is_protected(client):
    assert client.post("/api/event", json={"event": "share", "lat": 28.6, "lng": 77.2}).status_code == 204
    assert client.post("/api/event", json={"event": "share", "lat": 19.0, "lng": 72.9}).status_code == 204
    assert client.post("/api/event", json={"event": "hack"}).status_code == 400
    st = client.get("/api/stats").json()
    assert st["totals"]["share"] >= 2 and st["by_city"]["Mumbai"]["share"] >= 1
    assert client.post("/api/validation/run").status_code == 403
    assert client.get("/api/validation/summary").json()["samples"] >= 0


def test_run_stores_pairs(client, monkeypatch):
    s = app.state.settings
    saved = (s.datagov_api_key, s.validation_token)
    s.datagov_api_key, s.validation_token = "k", "tok"

    async def fake_stations(http, key):
        return [{"station": "ITO", "city": "Delhi", "state": "Delhi", "lat": 28.628, "lng": 77.241, "pm25": 210.0, "updated": "x"},
                {"station": "Bandra", "city": "Mumbai", "state": "Maharashtra", "lat": 19.06, "lng": 72.84, "pm25": 50.0, "updated": "x"}]

    async def fake_g(http, key, lat, lng):
        return (190.0 if lat > 25 else 60.0, 24)

    monkeypatch.setattr(v, "fetch_stations", fake_stations)
    monkeypatch.setattr(v, "google_24h", fake_g)
    try:
        r = client.post("/api/validation/run", headers={"X-Validation-Token": "tok"})
        assert r.status_code == 200 and r.json()["stored"] == 2
        summ = client.get("/api/validation/summary").json()
        assert summ["samples"] >= 2 and summ["google"]["mae"] is not None
    finally:
        s.datagov_api_key, s.validation_token = saved


def test_scheduler_can_call_run_without_browser_header():
    from fastapi.testclient import TestClient as TC
    with TC(app) as c:  # no X-Requested-With, like Cloud Scheduler
        assert c.post("/api/validation/run").status_code == 403  # token check, not CSRF
        assert "X-Requested-With" not in c.post("/api/validation/run").text


def test_datagov_failure_is_reported_not_500(client, monkeypatch):
    s = app.state.settings
    saved = (s.datagov_api_key, s.validation_token)
    s.datagov_api_key, s.validation_token = "k", "tok"

    async def boom(http, key):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(v, "fetch_stations", boom)
    try:
        r = client.post("/api/validation/run", headers={"X-Validation-Token": "tok"})
        assert r.status_code == 502 and "did not answer" in r.json()["detail"]
    finally:
        s.datagov_api_key, s.validation_token = saved
