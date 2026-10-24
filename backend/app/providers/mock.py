"""Synthetic providers for offline development and tests.

The pollution field is INVENTED: a Delhi-like background with made-up hotspots
near busy junctions and cleaner pockets near large green areas. It exists so the
pipeline, ranking and UI can be built and tested without a key. Never present
mock output as real air quality.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from ..geo import Point, bearing_deg, cumulative_distances, destination_point, encode_polyline, haversine_m
from ..models import LatLng, PlaceDetails, PlaceSuggestion, TravelMode, Usage
from .base import AQReading, ProviderError, RawRoute, RawStep

IST = timezone(timedelta(hours=5, minutes=30))

# (lat, lng, amplitude µg/m³, sigma metres). Positive = hotspot, negative = cleaner pocket.
_FIELD = [
    (28.6469, 77.3152, 190, 900),   # east Delhi interstate bus terminal area
    (28.6289, 77.2410, 170, 700),   # central arterial junction
    (28.6683, 77.1167, 150, 800),   # west Delhi ring road stretch
    (28.5713, 77.2590, 160, 650),   # south-east flyover junction
    (28.5308, 77.2713, 170, 900),   # industrial estate
    (28.5917, 77.1617, 140, 600),   # south-west interchange
    (28.6560, 77.2300, 150, 750),   # old city wholesale market area
    (28.5980, 77.2140, 230, 750),   # busy south-central arterial
    (28.5110, 77.0800, 150, 800),   # expressway toll plaza
    (28.5931, 77.2197, -70, 650),   # large heritage garden
    (28.6150, 77.1900, -65, 1400),  # central ridge forest
    (28.5355, 77.1688, -60, 900),   # urban forest south
    (28.6125, 77.2295, -50, 700),   # central lawns
]

_SPEED_KMH = {
    TravelMode.WALK: 4.8,
    TravelMode.BICYCLE: 13.0,
    TravelMode.TWO_WHEELER: 24.0,
    TravelMode.DRIVE: 21.0,
}

_PLACES = [
    ("mock-aiims", "AIIMS New Delhi", "Ansari Nagar, New Delhi", 28.5672, 77.2100),
    ("mock-cp", "Connaught Place", "New Delhi", 28.6315, 77.2167),
    ("mock-indiagate", "India Gate", "Rajpath, New Delhi", 28.6129, 77.2295),
    ("mock-hkv", "Hauz Khas Village", "South Delhi", 28.5535, 77.1940),
    ("mock-nehruplace", "Nehru Place", "South Delhi", 28.5494, 77.2511),
    ("mock-lajpat", "Lajpat Nagar Market", "South Delhi", 28.5677, 77.2433),
    ("mock-du", "Delhi University North Campus", "North Delhi", 28.6889, 77.2100),
    ("mock-ndls", "New Delhi Railway Station", "Paharganj, New Delhi", 28.6430, 77.2190),
    ("mock-saket", "Saket", "South Delhi", 28.5245, 77.2066),
    ("mock-dwarka", "Dwarka Sector 21", "South West Delhi", 28.5523, 77.0582),
    ("mock-cyber", "Cyber City", "Gurugram, Haryana", 28.4950, 77.0890),
    ("mock-noida18", "Sector 18", "Noida, Uttar Pradesh", 28.5700, 77.3260),
    ("mock-lodhi", "Lodhi Garden", "Lodhi Estate, New Delhi", 28.5931, 77.2197),
    ("mock-akshardham", "Akshardham", "East Delhi", 28.6127, 77.2773),
]


def synthetic_pm25(lat: float, lng: float, when: datetime) -> float:
    hour = when.astimezone(IST).hour
    diurnal = 1.0 + 0.22 * math.cos((hour - 9) / 24 * 2 * math.pi) + 0.18 * math.cos((hour - 21) / 24 * 2 * math.pi)
    value = 115.0
    for flat, flng, amp, sigma in _FIELD:
        d = haversine_m((lat, lng), (flat, flng))
        value += amp * math.exp(-(d * d) / (2 * sigma * sigma))
    # gentle large-scale gradient (worse towards the east and north-west)
    value += 25 * math.sin((lng - 77.0) * 6.0) + 10 * math.cos((lat - 28.6) * 9.0)
    return round(max(15.0, value * diurnal), 1)


def _bezier(a: Point, ctrl: Point, b: Point, n: int) -> list[Point]:
    pts = []
    for i in range(n + 1):
        t = i / n
        lat = (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * ctrl[0] + t**2 * b[0]
        lng = (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * ctrl[1] + t**2 * b[1]
        pts.append((lat, lng))
    return pts


def _wiggle(points: list[Point], amp_m: float, seed: float) -> list[Point]:
    """Small lateral jitter so mock routes look less like perfect curves."""
    out = [points[0]]
    for i in range(1, len(points) - 1):
        brg = bearing_deg(points[i - 1], points[i + 1])
        off = amp_m * math.sin(i * 0.9 + seed)
        out.append(destination_point(points[i], brg + 90, off))
    out.append(points[-1])
    return out


def _path(origin: Point, destination: Point, offset_frac: float, seed: float, via: list[Point] | None) -> list[Point]:
    stops = [origin, *(via or []), destination]
    pts: list[Point] = []
    for a, b in zip(stops, stops[1:]):
        d = haversine_m(a, b)
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        ctrl = destination_point(mid, bearing_deg(a, b) + 90, d * offset_frac) if offset_frac else mid
        n = max(8, int(d / 120))
        seg = _bezier(a, ctrl, b, n)
        pts.extend(seg if not pts else seg[1:])
    return _wiggle(pts, 25.0, seed)


class MockRoutes:
    async def compute_routes(self, origin, destination, mode, *, alternatives, via, departure_time, usage: Usage):
        usage.routes_calls += 1
        if haversine_m(origin, destination) < 30:
            raise ProviderError("Origin and destination are the same place.", 400)
        speed = _SPEED_KMH[mode] / 3.6
        traffic = 1.3 if mode in (TravelMode.DRIVE, TravelMode.TWO_WHEELER) else 1.0
        variants = [(0.0, 0.3, ["DEFAULT_ROUTE"])]
        if via:
            variants = [(0.0, 1.7, [])]
        elif alternatives:
            variants += [(0.22, 1.1, ["DEFAULT_ROUTE_ALTERNATE"]), (-0.2, 2.3, ["DEFAULT_ROUTE_ALTERNATE"])]
        out: list[RawRoute] = []
        for frac, seed, labels in variants:
            pts = _path(origin, destination, frac, seed, via)
            steps: list[RawStep] = []
            chunk = 12
            for i in range(0, len(pts) - 1, chunk):
                sp = pts[i : i + chunk + 1]
                dist = cumulative_distances(sp)[-1]
                steps.append(RawStep(points=sp, distance_m=dist, duration_s=dist / speed))
            total = sum(s.distance_m for s in steps)
            out.append(
                RawRoute(
                    points=pts,
                    encoded_polyline=encode_polyline(pts),
                    distance_m=round(total),
                    duration_s=round(sum(s.duration_s for s in steps) * traffic),
                    steps=steps,
                    labels=labels,
                )
            )
        return out


class MockAirQuality:
    async def current(self, lat, lng, usage: Usage):
        usage.aq_current_calls += 1
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        return self._reading(lat, lng, now, "current")

    async def forecast(self, lat, lng, start, end, usage: Usage):
        usage.aq_forecast_calls += 1
        out = {}
        t = start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        while t <= end:
            out[t] = self._reading(lat, lng, t, "forecast")
            t += timedelta(hours=1)
        return out

    @staticmethod
    def _reading(lat: float, lng: float, when: datetime, kind: str) -> AQReading:
        pm25 = synthetic_pm25(lat, lng, when)
        no2_ppb = round(18 + pm25 * 0.22, 1)
        return AQReading(
            pm25=pm25,
            pm10=round(pm25 * 1.75, 1),
            no2_ppb=no2_ppb,
            uaqi=max(0, int(100 - pm25 * 0.45)),
            observed_at=when,
            kind=kind,
            no2=round(no2_ppb * 46.0055 / 24.45, 1),
            o3=round(max(10.0, 80 - pm25 * 0.2), 1),
            co_mg=round(0.6 + pm25 * 0.01, 2),
            so2=12.0,
        )


class MockPlaces:
    async def autocomplete(self, query, session, bias, usage: Usage):
        usage.places_autocomplete_calls += 1
        q = query.strip().lower()
        hits = [p for p in _PLACES if q in p[1].lower() or q in p[2].lower()] if q else []
        return [PlaceSuggestion(place_id=p[0], primary=p[1], secondary=p[2]) for p in hits[:6]]

    async def details(self, place_id, session, usage: Usage):
        usage.places_details_calls += 1
        for pid, name, addr, lat, lng in _PLACES:
            if pid == place_id:
                return PlaceDetails(place_id=pid, name=name, address=addr, location=LatLng(lat=lat, lng=lng))
        raise ProviderError("Unknown place.", 404)
