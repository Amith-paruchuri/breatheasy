"""Google provider request building and response parsing, against a fake HTTP transport."""

import json
from datetime import datetime, timezone

import httpx
import pytest

from app.geo import encode_polyline
from app.models import TravelMode, Usage
from app.providers.google import GoogleAirQuality, GoogleClient, GooglePlaces, GoogleRoutes

PTS = [(28.56, 77.21), (28.57, 77.212), (28.58, 77.215)]


def handler(seen):
    def h(req: httpx.Request):
        body = json.loads(req.content) if req.content else None
        seen.append((req.url.path, req.headers.get("X-Goog-FieldMask"), body))
        p = req.url.path
        if p.endswith("computeRoutes"):
            step = lambda pts, sec: {"distanceMeters": 1200, "staticDuration": sec, "polyline": {"encodedPolyline": encode_polyline(pts)}}
            return httpx.Response(200, json={"routes": [{
                "duration": "900s", "distanceMeters": 2400, "routeLabels": ["DEFAULT_ROUTE"],
                "polyline": {"encodedPolyline": encode_polyline(PTS)},
                "legs": [{"steps": [step(PTS[:2], "400s"), step(PTS[1:], "350s")]}]}]})
        if p.endswith("currentConditions:lookup"):
            return httpx.Response(200, json={"dateTime": "2026-10-22T04:00:00Z", "indexes": [{"code": "uaqi", "aqi": 22}],
                "pollutants": [{"code": "pm25", "concentration": {"value": 142.3, "units": "MICROGRAMS_PER_CUBIC_METER"}},
                               {"code": "no2", "concentration": {"value": 41.2, "units": "PARTS_PER_BILLION"}}]})
        if p.endswith("forecast:lookup"):
            return httpx.Response(200, json={"hourlyForecasts": [{"dateTime": "2026-10-22T06:00:00Z",
                "pollutants": [{"code": "pm25", "concentration": {"value": 160, "units": "MICROGRAMS_PER_CUBIC_METER"}}]}]})
        if p.endswith("places:autocomplete"):
            return httpx.Response(200, json={"suggestions": [{"placePrediction": {"placeId": "abc",
                "structuredFormat": {"mainText": {"text": "AIIMS"}, "secondaryText": {"text": "Ansari Nagar"}}}}]})
        if "/places/" in p:
            return httpx.Response(200, json={"displayName": {"text": "AIIMS"}, "location": {"latitude": 28.5672, "longitude": 77.21}})
        return httpx.Response(400, json={"error": {"message": "bad"}})
    return h


@pytest.fixture
def client_and_log():
    seen = []
    c = GoogleClient("test-key", 5)
    c.http = httpx.AsyncClient(transport=httpx.MockTransport(handler(seen)))
    return c, seen


@pytest.mark.asyncio
async def test_routes_request_and_parse(client_and_log):
    c, seen = client_and_log
    u = Usage()
    r = await GoogleRoutes(c).compute_routes(PTS[0], PTS[-1], TravelMode.TWO_WHEELER, alternatives=True, via=None, departure_time=None, usage=u)
    assert r[0].duration_s == 900 and len(r[0].steps) == 2 and r[0].steps[0].duration_s == 400
    _, mask, body = seen[-1]
    assert "routes.legs.steps.staticDuration" in mask
    assert body["routingPreference"] == "TRAFFIC_AWARE" and body["computeAlternativeRoutes"] is True

    await GoogleRoutes(c).compute_routes(PTS[0], PTS[-1], TravelMode.WALK, alternatives=True, via=[(28.57, 77.22)], departure_time=None, usage=u)
    body = seen[-1][2]
    assert "routingPreference" not in body and "computeAlternativeRoutes" not in body
    assert body["intermediates"][0]["via"] is True
    assert u.routes_calls == 2


@pytest.mark.asyncio
async def test_air_quality_parse(client_and_log):
    c, seen = client_and_log
    u = Usage()
    aq = await GoogleAirQuality(c).current(28.56, 77.21, u)
    assert (aq.pm25, aq.no2_ppb, aq.uaqi) == (142.3, 41.2, 22)
    t = datetime(2026, 10, 22, 6, tzinfo=timezone.utc)
    fc = await GoogleAirQuality(c).forecast(28.56, 77.21, t, t, u)
    assert fc[t].pm25 == 160
    period = seen[-1][2]["period"]
    assert period["startTime"] < period["endTime"]


@pytest.mark.asyncio
async def test_places_parse(client_and_log):
    c, _ = client_and_log
    u = Usage()
    s = await GooglePlaces(c).autocomplete("aiims", "s1", (28.2, 76.8, 28.95, 77.75), u)
    assert s[0].primary == "AIIMS" and s[0].secondary == "Ansari Nagar"
    d = await GooglePlaces(c).details("abc", "s1", u)
    assert d.location.lat == 28.5672
