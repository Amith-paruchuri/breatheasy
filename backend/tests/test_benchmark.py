"""Trip benchmark helpers: trip picking, pins, overlap, summary."""

from app import benchmark as b


def test_pick_trips_respects_mode_distances():
    t = b.pick_trips(30, seed=1)
    assert len(t) == 30
    for city, mode, a, c in t:
        km = b._dist_m(a[1:], c[1:]) / 1000
        lo, hi = b.TRIP_KM[mode]
        assert lo <= km <= hi and city in b.PLACES


def test_overlap_and_waypoints():
    line = [(28.60 + i * 0.001, 77.20) for i in range(40)]  # ~4.4 km north
    assert b.overlap(line, line) == 1.0
    off = [(p[0], p[1] + 0.01) for p in line]  # ~1 km east
    assert b.overlap(off, line) == 0.0
    pins = b.waypoints(line, [], "WALK", 3)
    assert len(pins) == 3 and all(p in line for p in pins)
    assert len(b.waypoints(line, [], "WALK", 8)) == 3  # ~1 per 1.5 km


def test_summary():
    rows = [
        {"run_at": 1, "city": "Delhi-NCR", "differs": True, "fastest_pm25": 200, "chosen_pm25": 170, "fastest_bad_min": 20,
         "chosen_bad_min": 8, "chosen_min": 30, "fastest_min": 26, "fastest_road_min": 15, "chosen_road_min": 5,
         "fidelity3": 0.8, "fidelity8": 0.95},
        {"run_at": 1, "city": "Mumbai", "differs": False, "fastest_pm25": 60, "chosen_pm25": 60, "fastest_bad_min": 0,
         "chosen_bad_min": 0, "chosen_min": 20, "fastest_min": 20, "fastest_road_min": 3, "chosen_road_min": 3,
         "fidelity3": 1.0, "fidelity8": 1.0},
    ]
    s = b.summarize_trips(rows)
    assert s["trips"] == 2 and s["cleaner_found_pct"] == 50.0 and s["median_cleaner_pct"] == 15.0
    assert s["median_bad_min_avoided"] == 12 and s["fidelity_computer_90_pct"] == 100.0


def test_run_end_to_end_on_mock_providers(monkeypatch):
    import dataclasses

    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_accounts import H

    with TestClient(app, headers=H) as c:
        s = app.state.settings
        saved_tok, saved_p = s.validation_token, app.state.providers
        s.validation_token = "tok"
        app.state.providers = dataclasses.replace(saved_p, free=False)
        try:
            r = c.post("/api/validation/benchmark?n=6", headers={"X-Validation-Token": "tok"})
            assert r.status_code == 200, r.text
            assert r.json()["trips"] >= 1
            summ = c.get("/api/validation/summary").json()["benchmark"]
            assert summ["trips"] >= 1
        finally:
            s.validation_token, app.state.providers = saved_tok, saved_p
