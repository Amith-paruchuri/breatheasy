from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.geo import decode_polyline, encode_polyline, haversine_m, overlap_fraction
from app.models import Preference, Usage
from app.providers.base import AQReading, RawRoute, RawStep
from app.services.airquality import AQCache, AQService
from app.services.exposure import compute_exposure
from app.services.ranking import Scored, pick
from app.services.sampling import build_timed_path, split_segments


def test_polyline_roundtrip_google_example():
    # Example from Google's polyline algorithm documentation
    pts = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert pts == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
    assert encode_polyline(pts) == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"


def test_haversine_delhi_scale():
    # AIIMS to Connaught Place is roughly 7 km as the crow flies
    assert 6500 < haversine_m((28.5672, 77.2100), (28.6315, 77.2167)) < 7700


def _route(n=50, duration=1200.0):
    pts = [(28.55 + i * 0.001, 77.20) for i in range(n)]
    steps = [
        RawStep(points=pts[:25], distance_m=0, duration_s=300),
        RawStep(points=pts[24:], distance_m=0, duration_s=900),  # slower second half
    ]
    return RawRoute(points=pts, encoded_polyline=encode_polyline(pts), distance_m=0, duration_s=duration, steps=steps)


def test_segments_cover_route_and_time():
    tp = build_timed_path(_route(duration=2400))  # traffic doubles static time
    segs = split_segments(tp, 400)
    assert abs(sum(s.duration_s for s in segs) - 2400) < 1e-6
    assert abs(segs[0].start_s) < 1e-9
    # second half is slower, so its segments must be longer in time
    assert segs[-1].duration_s > segs[0].duration_s * 2
    for s in segs:
        assert len(s.path) >= 2


def _reading(v):
    return AQReading(pm25=v, pm10=v * 2, no2_ppb=None, uaqi=None, observed_at=datetime.now(timezone.utc), kind="current")


def test_exposure_is_concentration_times_time():
    tp = build_timed_path(_route(duration=600))
    segs = split_segments(tp, 10_000)  # single segment, 10 min
    ex = compute_exposure(segs, [_reading(100.0)], 60)
    assert ex.exposure_pm25 == pytest.approx(1000.0)
    assert ex.minutes_above_reference == pytest.approx(10.0)
    assert ex.coverage == 1.0


def test_exposure_fills_gaps_with_mean():
    tp = build_timed_path(_route(duration=600))
    segs = split_segments(tp, 1500)
    readings = [_reading(100.0)] + [None] * (len(segs) - 1)
    ex = compute_exposure(segs, readings, 60)
    assert ex.exposure_pm25 == pytest.approx(1000.0, rel=1e-6)
    assert ex.coverage < 1


def test_ranking_balanced_and_threshold():
    fast = Scored("a", 1800, 3000.0, set())
    slightly_cleaner = Scored("b", 1860, 2900.0, set())  # 3% cleaner, +1 min
    much_cleaner = Scored("c", 2100, 2100.0, set())  # 30% cleaner, +5 min
    too_slow = Scored("d", 3600, 1000.0, set())  # outside 10-min budget
    routes = [fast, slightly_cleaner, much_cleaner, too_slow]

    rec, f, c = pick(routes, Preference.BALANCED, 10, 1.5, 10)
    assert (rec, f) == ("c", "a") and c["meaningful"]

    rec, _, _ = pick(routes, Preference.CLEANEST, 10, 1.5, 10)
    assert rec == "c"  # d is out of budget

    rec, _, c = pick(routes, Preference.FASTEST, 10, 1.5, 10)
    assert rec == "a" and "lower" in c["message"]

    # below-threshold improvement falls back to fastest
    rec, _, c = pick([fast, slightly_cleaner], Preference.CLEANEST, 10, 1.5, 10)
    assert rec == "a" and not c["meaningful"]


def test_ranking_balanced_rejects_expensive_detour():
    fast = Scored("a", 1800, 3000.0, set())
    costly = Scored("b", 2400, 2550.0, set())  # 15% cleaner for 10 min: 15 - 15 = 0
    rec, _, c = pick([fast, costly], Preference.BALANCED, 15, 1.5, 10)
    assert rec == "a"
    assert "Cleanest" in c["message"]


def test_overlap_detects_duplicates():
    a = [(28.55 + i * 0.001, 77.20) for i in range(30)]
    b = [(28.55 + i * 0.001, 77.2001) for i in range(30)]  # ~10 m apart
    c = [(28.55 + i * 0.001, 77.23) for i in range(30)]  # ~3 km apart
    assert overlap_fraction(a, b) > 0.95
    assert overlap_fraction(a, c) == 0.0


class CountingAQ:
    def __init__(self):
        self.current_calls = 0
        self.forecast_calls = 0

    async def current(self, lat, lng, usage):
        self.current_calls += 1
        return _reading(50.0)

    async def forecast(self, lat, lng, start, end, usage):
        self.forecast_calls += 1
        out = {}
        t = start
        while t <= end:
            out[t] = AQReading(80.0, None, None, None, t, "forecast")
            t += timedelta(hours=1)
        return out


@pytest.mark.asyncio
async def test_aq_dedupes_cells_and_splits_current_vs_forecast():
    s = Settings(provider="mock")
    prov = CountingAQ()
    svc = AQService(prov, s, AQCache(600))
    now = datetime(2026, 10, 22, 4, 10, tzinfo=timezone.utc)
    q = [
        (28.5672, 77.2100, now),  # same cell twice, current hour
        (28.5673, 77.2101, now + timedelta(minutes=5)),
        (28.6000, 77.2500, now + timedelta(hours=2)),  # later hour -> forecast
    ]
    usage = Usage()
    out = await svc.lookup(q, now, usage)
    assert prov.current_calls == 1 and prov.forecast_calls == 1
    assert [r.pm25 for r in out] == [50.0, 50.0, 80.0]
    # second identical request is fully cached
    await svc.lookup(q, now, usage)
    assert prov.current_calls == 1 and prov.forecast_calls == 1
    assert usage.aq_cache_hits == 2


def test_env_example_loads(tmp_path, monkeypatch):
    """The shipped .env.example must parse as-is (blank price lines included)."""
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / ".env.example"
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROVIDER", raising=False)
    (tmp_path / ".env").write_text(src.read_text())
    s = Settings()
    assert s.provider == "open" and s.price_aq_per_1000_usd is None and s.route_cache_ttl_s == 120
