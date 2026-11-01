"""Google Maps Platform integrations: Routes API, Air Quality API, Places API (New).

Enable these four APIs in your Google Cloud project:
  Routes API, Air Quality API, Places API (New), Maps JavaScript API (frontend only)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from ..aqi import ppb_to_ugm3
from ..geo import decode_polyline
from ..models import LatLng, PlaceDetails, PlaceSuggestion, TravelMode, Usage
from .base import AQReading, ProviderError, RawRoute, RawStep

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
AQ_CURRENT_URL = "https://airquality.googleapis.com/v1/currentConditions:lookup"
AQ_FORECAST_URL = "https://airquality.googleapis.com/v1/forecast:lookup"
PLACES_AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
PLACES_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

ROUTE_FIELD_MASK = ",".join(
    [
        "routes.duration",
        "routes.distanceMeters",
        "routes.polyline.encodedPolyline",
        "routes.routeLabels",
        "routes.legs.steps.distanceMeters",
        "routes.legs.steps.staticDuration",
        "routes.legs.steps.polyline.encodedPolyline",
    ]
)


def _seconds(value: str | None) -> float:
    if not value:
        return 0.0
    return float(value.rstrip("s"))


def _latlng(p: tuple[float, float]) -> dict:
    return {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _status_for(code: int) -> int:
    """Map Google HTTP status to ours. Auth/quota problems must NOT look like
    "no data here" (400), so they surface as 503/429 and trigger the fallback."""
    if code in (401, 403):
        return 503  # key invalid/restricted, API not enabled, billing off
    if code == 429:
        return 429  # quota exceeded
    if code >= 500:
        return 502
    return 404 if code == 404 else 400


def _error_message(resp: httpx.Response, api: str) -> str:
    try:
        detail = resp.json().get("error", {}).get("message", "")
    except ValueError:
        detail = resp.text[:200]
    return f"{api} returned HTTP {resp.status_code}: {detail}".strip()


class GoogleClient:
    def __init__(self, api_key: str, timeout_s: float):
        if not api_key:
            raise ProviderError(
                "PROVIDER=google but GOOGLE_MAPS_SERVER_KEY is empty. Set it in backend/.env.", 500
            )
        self.key = api_key
        self.http = httpx.AsyncClient(timeout=timeout_s)

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _post(self, url: str, body: dict, api: str, field_mask: str | None = None) -> dict:
        headers = {"Content-Type": "application/json", "X-Goog-Api-Key": self.key}
        if field_mask:
            headers["X-Goog-FieldMask"] = field_mask
        try:
            resp = await self.http.post(url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{api} unreachable: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(_error_message(resp, api), _status_for(resp.status_code))
        return resp.json()


class GoogleRoutes:
    def __init__(self, client: GoogleClient):
        self.c = client

    async def compute_routes(self, origin, destination, mode, *, alternatives, via, departure_time, usage: Usage):
        body: dict = {
            "origin": _latlng(origin),
            "destination": _latlng(destination),
            "travelMode": mode.value,
            "polylineQuality": "HIGH_QUALITY",
            "languageCode": "en-IN",
            "regionCode": "IN",
            "units": "METRIC",
        }
        if mode in (TravelMode.DRIVE, TravelMode.TWO_WHEELER):
            body["routingPreference"] = "TRAFFIC_AWARE"
            if departure_time and departure_time > datetime.now(timezone.utc) + timedelta(minutes=1):
                body["departureTime"] = departure_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if via:
            # Alternatives are never returned when intermediates are present.
            body["intermediates"] = [{**_latlng(p), "via": True} for p in via]
        elif alternatives:
            body["computeAlternativeRoutes"] = True

        usage.routes_calls += 1
        data = await self.c._post(ROUTES_URL, body, "Routes API", ROUTE_FIELD_MASK)

        routes: list[RawRoute] = []
        for r in data.get("routes", []):
            enc = r.get("polyline", {}).get("encodedPolyline", "")
            if not enc:
                continue
            steps = []
            for leg in r.get("legs", []):
                for s in leg.get("steps", []):
                    s_enc = s.get("polyline", {}).get("encodedPolyline")
                    if not s_enc:
                        continue
                    steps.append(
                        RawStep(
                            points=decode_polyline(s_enc),
                            distance_m=float(s.get("distanceMeters", 0)),
                            duration_s=_seconds(s.get("staticDuration")),
                        )
                    )
            routes.append(
                RawRoute(
                    points=decode_polyline(enc),
                    encoded_polyline=enc,
                    distance_m=float(r.get("distanceMeters", 0)),
                    duration_s=_seconds(r.get("duration")),
                    steps=steps,
                    labels=list(r.get("routeLabels", [])),
                )
            )
        return routes


def _parse_aq(payload: dict, kind: str) -> AQReading:
    conc: dict[str, tuple[float, str]] = {}
    for p in payload.get("pollutants", []) or []:
        c = p.get("concentration") or {}
        if "value" in c:
            conc[p.get("code", "")] = (float(c["value"]), c.get("units", ""))
    uaqi = None
    for idx in payload.get("indexes", []) or []:
        if idx.get("code") == "uaqi":
            uaqi = idx.get("aqi")

    def ug(code: str) -> float | None:
        v = conc.get(code)
        if not v:
            return None
        value, units = v
        return value if units in ("MICROGRAMS_PER_CUBIC_METER", "") else None

    def gas_ug(code: str) -> float | None:
        v = conc.get(code)
        if not v:
            return None
        value, units = v
        if units == "PARTS_PER_BILLION":
            return ppb_to_ugm3(code, value)
        if units == "MICROGRAMS_PER_CUBIC_METER":
            return value
        return None

    no2 = conc.get("no2")
    co = gas_ug("co")
    return AQReading(
        pm25=ug("pm25"),
        pm10=ug("pm10"),
        no2_ppb=no2[0] if no2 and no2[1] == "PARTS_PER_BILLION" else None,
        uaqi=uaqi,
        observed_at=_parse_time(payload.get("dateTime")),
        kind=kind,
        no2=gas_ug("no2"),
        o3=gas_ug("o3"),
        co_mg=co / 1000 if co is not None else None,
        so2=gas_ug("so2"),
    )


class GoogleAirQuality:
    def __init__(self, client: GoogleClient):
        self.c = client

    async def current(self, lat, lng, usage: Usage):
        usage.aq_current_calls += 1
        body = {
            "location": {"latitude": lat, "longitude": lng},
            "extraComputations": ["POLLUTANT_CONCENTRATION"],
            "universalAqi": True,
            "languageCode": "en",
        }
        try:
            data = await self.c._post(AQ_CURRENT_URL, body, "Air Quality API")
        except ProviderError as exc:
            if exc.status == 400:  # e.g. location not covered: treat as missing data
                return None
            raise
        return _parse_aq(data, "current")

    async def forecast(self, lat, lng, start, end, usage: Usage):
        out: dict[datetime, AQReading] = {}
        end = end + timedelta(hours=1)  # request a period strictly after start, covering the last hour
        body: dict = {
            "location": {"latitude": lat, "longitude": lng},
            "period": {
                "startTime": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "endTime": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
            "extraComputations": ["POLLUTANT_CONCENTRATION"],
            "universalAqi": True,
            "languageCode": "en",
            "pageSize": max(1, int((end - start).total_seconds() // 3600)),
        }
        for _ in range(4):  # follow at most a few pages
            usage.aq_forecast_calls += 1
            try:
                data = await self.c._post(AQ_FORECAST_URL, body, "Air Quality API (forecast)")
            except ProviderError as exc:
                if exc.status == 400:
                    return out
                raise
            for h in data.get("hourlyForecasts", []) or []:
                reading = _parse_aq(h, "forecast")
                hour = reading.observed_at.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
                out[hour] = reading
            token = data.get("nextPageToken")
            if not token:
                break
            body["pageToken"] = token
        return out


class GooglePlaces:
    def __init__(self, client: GoogleClient):
        self.c = client

    async def autocomplete(self, query, session, bias, usage: Usage):
        south, west, north, east = bias
        body: dict = {
            "input": query,
            "includedRegionCodes": ["in"],
            "languageCode": "en",
            "locationRestriction": {
                "rectangle": {
                    "low": {"latitude": south, "longitude": west},
                    "high": {"latitude": north, "longitude": east},
                }
            },
        }
        if session:
            body["sessionToken"] = session
        usage.places_autocomplete_calls += 1
        data = await self.c._post(PLACES_AUTOCOMPLETE_URL, body, "Places API")
        out: list[PlaceSuggestion] = []
        for s in data.get("suggestions", []):
            p = s.get("placePrediction")
            if not p:
                continue
            fmt = p.get("structuredFormat", {})
            out.append(
                PlaceSuggestion(
                    place_id=p.get("placeId", ""),
                    primary=fmt.get("mainText", {}).get("text") or p.get("text", {}).get("text", ""),
                    secondary=fmt.get("secondaryText", {}).get("text", ""),
                )
            )
        return out

    async def details(self, place_id, session, usage: Usage):
        headers = {
            "X-Goog-Api-Key": self.c.key,
            # Essentials fields only: displayName would bill the pricier Place Details Pro SKU.
            # The app labels the place with the suggestion text the person tapped.
            "X-Goog-FieldMask": "id,formattedAddress,location",
        }
        params = {"sessionToken": session} if session else None
        usage.places_details_calls += 1
        try:
            resp = await self.c.http.get(
                PLACES_DETAILS_URL.format(place_id=place_id), headers=headers, params=params
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Places API unreachable: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(_error_message(resp, "Places API"), _status_for(resp.status_code))
        d = resp.json()
        loc = d.get("location", {})
        return PlaceDetails(
            place_id=place_id,
            name=d.get("displayName", {}).get("text", "") or d.get("formattedAddress", "").split(",")[0],
            address=d.get("formattedAddress", ""),
            location=LatLng(lat=loc.get("latitude", 0.0), lng=loc.get("longitude", 0.0)),
        )
