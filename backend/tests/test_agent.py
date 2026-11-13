import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.agent import parse_rules
from app.models import TravelMode

AIIMS = {"lat": 28.5672, "lng": 77.2100}

@pytest.fixture(scope="module")
def client():
    with TestClient(app, headers={"X-Requested-With": "breatheasy"}) as c:
        yield c

def test_parsing_rules():
    p1 = parse_rules("reach AIIMS by 9 am on my cycle")
    assert p1["destination"] == "AIIMS"
    assert p1["mode"] == TravelMode.BICYCLE
    assert p1["arrive_by"].hour == 9
    
    p2 = parse_rules("I have asthma and need to go to Hauz Khas from AIIMS by 14:30")
    assert p2["destination"] == "Hauz Khas"
    assert p2["origin"] == "AIIMS"
    assert p2["mode"] == TravelMode.DRIVE  # car unless another mode is named
    assert p2["arrive_by"].hour == 14
    assert parse_rules("walk to Lodhi Garden by 7 am")["mode"] == TravelMode.WALK
    assert parse_rules("reach India Gate on foot")["mode"] == TravelMode.WALK
    assert p2["arrive_by"].minute == 30
    assert "asthma" in p2["conditions"]

    p3 = parse_rules("taxi to airport")
    assert p3["destination"] == "airport"
    assert p3["mode"] == TravelMode.DRIVE

def test_agent_endpoint(client):
    r = client.post("/api/agent", json={"query": "reach Connaught Place by 11 pm", "origin": AIIMS})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Leave at" in body["verdict"]
    assert body["plan"]["recommended_id"]

def test_agent_reuses_routes(client):
    # Ensure routing engine is called once even for multiple departure trials.
    # A single generate_candidates call with 2 detours makes 3 Routes API calls.
    r = client.post("/api/agent", json={"query": "reach Connaught Place by 9 am", "origin": AIIMS})
    assert r.status_code == 200, r.text
    body = r.json()
    # If reuse failed, this would be 3 + 3 * trials (approx 21).
    assert body["plan"]["usage"]["routes_calls"] <= 3

def test_agent_plans_toggle(client):
    orig = app.state.settings.plans_enabled
    try:
        app.state.settings.plans_enabled = True
        r = client.post("/api/agent", json={"query": "reach Connaught Place by 9 am", "origin": AIIMS})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["plan"]["plan"]["plan"] == "anonymous"
        # In mock mode with plans on, force_open is true, but mock provider
        # has no secondary, so it stays on "mock". Just check it didn't crash.
        assert body["plan"]["usage"]["aq_source"] == "mock"

        app.state.settings.plans_enabled = False
        r = client.post("/api/agent", json={"query": "reach Connaught Place by 9 am", "origin": AIIMS})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["plan"]["plan"] is None
        assert body["plan"]["usage"]["aq_source"] == "mock"
    finally:
        app.state.settings.plans_enabled = orig
