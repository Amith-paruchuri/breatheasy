import pytest
from fastapi.testclient import TestClient

from app.main import app

AIIMS = {"lat": 28.5672, "lng": 77.2100}
CP = {"lat": 28.6315, "lng": 77.2167}


@pytest.fixture(scope="module")
def client():
    with TestClient(app, headers={"X-Requested-With": "breatheasy"}) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["provider"] == "mock"


@pytest.mark.parametrize("mode", ["WALK", "BICYCLE", "TWO_WHEELER", "DRIVE"])
def test_routes_all_modes(client, mode):
    r = client.post("/api/routes", json={"origin": AIIMS, "destination": CP, "mode": mode})
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {x["id"] for x in body["routes"]}
    assert body["recommended_id"] in ids and body["fastest_id"] in ids
    assert len(body["routes"]) >= 3  # primary + alternatives + at least one detour
    assert body["routes"][0]["id"] == body["recommended_id"]
    for route in body["routes"]:
        assert route["exposure_pm25"] > 0
        assert route["coverage"] == 1.0
        assert route["segments"]
    fastest = next(x for x in body["routes"] if x["id"] == body["fastest_id"])
    assert fastest["delta_exposure_pct"] == 0
    assert body["data"]["mock"] is True
    assert body["usage"]["routes_calls"] >= 1


def test_preferences_change_choice_consistently(client):
    out = {}
    for pref in ("fastest", "balanced", "cleanest"):
        body = client.post(
            "/api/routes",
            json={"origin": AIIMS, "destination": CP, "mode": "WALK", "preference": pref, "max_extra_minutes": 30},
        ).json()
        rec = next(x for x in body["routes"] if x["id"] == body["recommended_id"])
        out[pref] = rec
    assert out["fastest"]["extra_minutes"] == 0
    assert out["cleanest"]["exposure_pm25"] <= out["balanced"]["exposure_pm25"] <= out["fastest"]["exposure_pm25"]


def test_outside_region_warns(client):
    # Mumbai is inside the service area (India): no warning
    body = client.post(
        "/api/routes", json={"origin": {"lat": 19.07, "lng": 72.87}, "destination": {"lat": 19.10, "lng": 72.90}}
    ).json()
    assert not any("outside" in w for w in body["warnings"])
    # outside India: warned
    body = client.post(
        "/api/routes", json={"origin": {"lat": 25.20, "lng": 55.27}, "destination": {"lat": 25.22, "lng": 55.30}}
    ).json()
    assert any("outside" in w for w in body["warnings"])


def test_places_mock(client):
    r = client.get("/api/places/autocomplete", params={"q": "aiims"})
    assert r.status_code == 200 and r.json()[0]["place_id"] == "mock-aiims"
    d = client.get("/api/places/mock-aiims").json()
    assert abs(d["location"]["lat"] - 28.5672) < 1e-6


def test_same_point_is_400(client):
    r = client.post("/api/routes", json={"origin": AIIMS, "destination": AIIMS})
    assert r.status_code == 400


def test_rerank_reuses_candidates(client):
    req = {"origin": {"lat": 28.60, "lng": 77.20}, "destination": {"lat": 28.62, "lng": 77.24}, "mode": "DRIVE"}
    first = client.post("/api/routes", json={**req, "preference": "fastest"}).json()
    second = client.post("/api/routes", json={**req, "preference": "cleanest"}).json()
    assert first["usage"]["routes_calls"] >= 1
    assert second["usage"]["routes_calls"] == 0
    assert second["usage"]["aq_current_calls"] + second["usage"]["aq_forecast_calls"] == 0
