"""Keyless open-data providers (PROVIDER=open). Real data, no account, no billing.

- Routing: OSRM servers run by FOSSGIS (routing.openstreetmap.de), OpenStreetMap data,
  with separate car / bike / foot profiles. Two-wheelers use the car profile.
- Air quality: Open-Meteo Air Quality API (Copernicus CAMS model). Many points are
  fetched in ONE request. Over India it uses the CAMS global model, roughly a
  40 km grid, so it captures time-of-day and day-to-day changes far better than
  street-to-street differences. Treat route rankings from it as indicative.
- Place search: Photon (komoot), OpenStreetMap-based geocoder.

These are free public services with fair-use policies: fine for a prototype and a
small pilot, not for a public launch. Self-host OSRM / Photon or move to
PROVIDER=google before that.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote, unquote

import httpx

from ..geo import decode_polyline
from ..models import LatLng, PlaceDetails, PlaceSuggestion, TravelMode, Usage
from .base import AQReading, ProviderError, RawRoute, RawStep

OSRM_PROFILE = {
    TravelMode.WALK: "routed-foot",
    TravelMode.BICYCLE: "routed-bike",
    TravelMode.TWO_WHEELER: "routed-car",
    TravelMode.DRIVE: "routed-car",
}
# OSRM's car profile has no live traffic. Delhi peak traffic is much slower than
# free-flow, so car-profile durations are scaled up. Tune against real trips.
TRAFFIC_FACTOR = {TravelMode.DRIVE: 1.6, TravelMode.TWO_WHEELER: 1.35}


def _client(timeout_s: float, user_agent: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout_s, headers={"User-Agent": user_agent})


class OpenRoutes:
    def __init__(self, http: httpx.AsyncClient, base_url: str):
        self.http = http
        self.base = base_url.rstrip("/")

    async def compute_routes(self, origin, destination, mode, *, alternatives, via, departure_time, usage: Usage):
        pts = [origin, *(via or []), destination]
        coords = ";".join(f"{p[1]:.6f},{p[0]:.6f}" for p in pts)
        url = f"{self.base}/{OSRM_PROFILE[mode]}/route/v1/driving/{coords}"
        params = {
            "overview": "full",
            "geometries": "polyline",
            "steps": "true",
            # alternatives only work for plain two-point requests
            "alternatives": "3" if alternatives and not via else "false",
        }
        usage.routes_calls += 1
        try:
            resp = await self.http.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenStreetMap routing unreachable: {exc}") from exc
        try:
            data = resp.json()
        except ValueError:
            raise ProviderError(f"OpenStreetMap routing returned HTTP {resp.status_code}") from None
        code = data.get("code")
        if code in ("NoRoute", "NoSegment"):
            raise ProviderError("No route found between these points for this travel mode.", 404)
        if resp.status_code >= 400 or code != "Ok":
            raise ProviderError(f"OpenStreetMap routing error: {data.get('message') or code or resp.status_code}")

        factor = TRAFFIC_FACTOR.get(mode, 1.0)
        out: list[RawRoute] = []
        for i, r in enumerate(data.get("routes", [])):
            enc = r.get("geometry")
            if not isinstance(enc, str) or not enc:
                continue
            steps: list[RawStep] = []
            for leg in r.get("legs", []):
                for s in leg.get("steps", []):
                    g = s.get("geometry")
                    if isinstance(g, str) and g:
                        steps.append(
                            RawStep(
                                points=decode_polyline(g),
                                distance_m=float(s.get("distance", 0)),
                                duration_s=float(s.get("duration", 0)),
                            )
                        )
            out.append(
                RawRoute(
                    points=decode_polyline(enc),
                    encoded_polyline=enc,
                    distance_m=float(r.get("distance", 0)),
                    duration_s=float(r.get("duration", 0)) * factor,
                    steps=steps,
                    labels=["DEFAULT_ROUTE" if i == 0 else "DEFAULT_ROUTE_ALTERNATE"],
                )
            )
        return out


def _hour(s: str) -> datetime:
    # Open-Meteo returns local-looking ISO strings; we always request timezone=GMT.
    t = datetime.fromisoformat(s.replace("Z", ""))
    return t.replace(tzinfo=timezone.utc, minute=0, second=0, microsecond=0)


def _val(block: dict, key: str, i: int | None = None) -> float | None:
    v = block.get(key)
    if i is not None:
        v = v[i] if isinstance(v, list) and i < len(v) else None
    return float(v) if isinstance(v, (int, float)) else None


class OpenAirQuality:
    """Implements `batch_hourly`, which AQService prefers over per-point calls."""

    MAX_POINTS_PER_CALL = 50

    def __init__(self, http: httpx.AsyncClient, url: str):
        self.http = http
        self.url = url

    async def _fetch(self, points: list[tuple[float, float]], days: int, usage: Usage) -> list[dict]:
        params = {
            "latitude": ",".join(f"{p[0]:.4f}" for p in points),
            "longitude": ",".join(f"{p[1]:.4f}" for p in points),
            "current": "pm2_5,pm10,nitrogen_dioxide,ozone,carbon_monoxide,sulphur_dioxide",
            "hourly": "pm2_5,pm10,nitrogen_dioxide,ozone,carbon_monoxide,sulphur_dioxide",
            "timezone": "GMT",
            "forecast_days": str(max(1, min(days, 5))),
        }
        usage.aq_current_calls += 1
        try:
            resp = await self.http.get(self.url, params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Open-Meteo air quality unreachable: {exc}") from exc
        if resp.status_code >= 400:
            try:
                reason = resp.json().get("reason", "")
            except ValueError:
                reason = resp.text[:200]
            raise ProviderError(f"Open-Meteo air quality error {resp.status_code}: {reason}")
        data = resp.json()
        return data if isinstance(data, list) else [data]

    async def batch_hourly(
        self, points: list[tuple[float, float]], days: int, usage: Usage
    ) -> list[tuple[AQReading | None, dict[datetime, AQReading]]]:
        """For each point: (current reading, {utc hour: forecast reading})."""
        results: list[tuple[AQReading | None, dict[datetime, AQReading]]] = []
        for i in range(0, len(points), self.MAX_POINTS_PER_CALL):
            chunk = points[i : i + self.MAX_POINTS_PER_CALL]
            payloads = await self._fetch(chunk, days, usage)
            if len(payloads) != len(chunk):
                raise ProviderError("Open-Meteo returned an unexpected number of locations.")
            for p in payloads:
                cur = p.get("current") or {}
                current = None
                if cur.get("time"):
                    co = _val(cur, "carbon_monoxide")
                    current = AQReading(
                        pm25=_val(cur, "pm2_5"),
                        pm10=_val(cur, "pm10"),
                        no2_ppb=None,
                        uaqi=None,
                        observed_at=datetime.fromisoformat(cur["time"].replace("Z", "")).replace(tzinfo=timezone.utc),
                        kind="current",
                        no2=_val(cur, "nitrogen_dioxide"),
                        o3=_val(cur, "ozone"),
                        co_mg=co / 1000 if co is not None else None,  # Open-Meteo gives µg/m³
                        so2=_val(cur, "sulphur_dioxide"),
                    )
                hourly: dict[datetime, AQReading] = {}
                h = p.get("hourly") or {}
                for j, t in enumerate(h.get("time", []) or []):
                    pm25 = _val(h, "pm2_5", j)
                    if pm25 is None:
                        continue
                    hr = _hour(t)
                    co = _val(h, "carbon_monoxide", j)
                    hourly[hr] = AQReading(
                        pm25, _val(h, "pm10", j), None, None, hr, "forecast",
                        no2=_val(h, "nitrogen_dioxide", j),
                        o3=_val(h, "ozone", j),
                        co_mg=co / 1000 if co is not None else None,
                        so2=_val(h, "sulphur_dioxide", j),
                    )
                results.append((current, hourly))
        return results

    # Per-point interface, for completeness / other callers.
    async def current(self, lat, lng, usage: Usage):
        return (await self.batch_hourly([(lat, lng)], 1, usage))[0][0]

    async def forecast(self, lat, lng, start, end, usage: Usage):
        days = int((end - datetime.now(timezone.utc)).total_seconds() // 86400) + 2
        hourly = (await self.batch_hourly([(lat, lng)], days, usage))[0][1]
        return {k: v for k, v in hourly.items() if start <= k <= end}


def encode_place_id(lat: float, lng: float, name: str) -> str:
    return f"geo:{lat:.6f},{lng:.6f}:{quote(name, safe='')}"


def decode_place_id(pid: str) -> PlaceDetails:
    try:
        _, coords, name = pid.split(":", 2)
        lat_s, lng_s = coords.split(",")
        name = unquote(name)
        return PlaceDetails(place_id=pid, name=name, address="", location=LatLng(lat=float(lat_s), lng=float(lng_s)))
    except (ValueError, TypeError):
        raise ProviderError("Unknown place id.", 404) from None


class OpenPlaces:
    def __init__(self, http: httpx.AsyncClient, url: str):
        self.http = http
        self.url = url

    async def autocomplete(self, query, session, bias, usage: Usage):
        south, west, north, east = bias
        params = {
            "q": query,
            "limit": "7",
            "lang": "en",
            "bbox": f"{west},{south},{east},{north}",
            "lat": f"{(south + north) / 2:.4f}",
            "lon": f"{(west + east) / 2:.4f}",
        }
        usage.places_autocomplete_calls += 1
        try:
            resp = await self.http.get(self.url, params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Place search unreachable: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"Place search error {resp.status_code}")
        out: list[PlaceSuggestion] = []
        seen: set[str] = set()
        for f in resp.json().get("features", []):
            coords = (f.get("geometry") or {}).get("coordinates") or []
            props = f.get("properties") or {}
            if len(coords) < 2:
                continue
            name = props.get("name") or props.get("street") or ""
            if not name:
                continue
            area = [props.get(k) for k in ("district", "locality", "city", "state") if props.get(k)]
            secondary = ", ".join(dict.fromkeys(a for a in area if a != name))
            key = f"{name}|{secondary}"
            if key in seen:
                continue
            seen.add(key)
            out.append(
                PlaceSuggestion(
                    place_id=encode_place_id(coords[1], coords[0], name),
                    primary=name,
                    secondary=secondary,
                )
            )
        return out[:6]

    async def details(self, place_id, session, usage: Usage):
        return decode_place_id(place_id)  # coordinates travel inside the id: no extra call
