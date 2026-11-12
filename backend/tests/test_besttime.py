"""Best time to leave."""

import asyncio
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.besttime import OFFSETS_MIN, TimePoint, best_time
from app.main import app
from app.providers.base import AQReading
from app.services.planner import IST
from tests.test_accounts import H


class FakeAQ:
    """PM2.5 falls by 20 per hour after now; records the window it was asked for."""

    def cell_of(self, lat, lng, scale=1):
        return (round(lat * 100 / scale), round(lng * 100 / scale))

    async def lookup(self, queries, now, usage, scale=1, current_window_min=None):
        self.window = current_window_min
        usage.aq_source = "google"
        out = []
        for _, _, at in queries:
            hrs = max(0, int((at - now).total_seconds() // 3600))
            out.append(AQReading(pm25=200 - 20 * hrs, pm10=None, no2_ppb=None, uaqi=None, observed_at=at, kind="forecast"))
        return out


def test_best_time_picks_the_cleanest_departure():
    now = datetime(2026, 11, 12, 17, 0, tzinfo=IST)
    pts = [TimePoint(lat=28.6, lng=77.2, offset_s=i * 300, duration_s=300) for i in range(6)]
    aq = FakeAQ()
    r, _ = asyncio.run(best_time(pts, aq, now))
    assert [s.offset_min for s in r.slots] == list(OFFSETS_MIN)
    assert r.best_offset_min == 120 and r.cleaner_pct and r.cleaner_pct > 15
    assert r.slots[0].depart == "17:00" and r.slots[-1].depart == (now + timedelta(minutes=120)).strftime("%H:%M")
    assert aq.window == 0  # later hours must use the forecast, not current conditions


def test_endpoint_on_mock_providers():
    with TestClient(app, headers=H) as c:
        body = {"mode": "WALK", "points": [{"lat": 28.6 + i * 0.002, "lng": 77.2, "offset_s": i * 120, "duration_s": 120}
                                           for i in range(10)]}
        r = c.post("/api/best-time", json=body)
        assert r.status_code == 200, r.text
        assert len(r.json()["slots"]) == 5
