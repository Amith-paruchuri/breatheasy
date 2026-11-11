"""API request/response schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class LatLng(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class TravelMode(str, Enum):
    WALK = "WALK"
    BICYCLE = "BICYCLE"
    TWO_WHEELER = "TWO_WHEELER"
    DRIVE = "DRIVE"


class Preference(str, Enum):
    CLEANEST_AIR = "cleanest_air"  # lowest average AQI, even if it takes much longer
    CLEANEST = "cleanest"  # lowest total exposure (dose) within the time budget
    BALANCED = "balanced"
    FASTEST = "fastest"


class RouteRequest(BaseModel):
    origin: LatLng
    destination: LatLng
    mode: TravelMode = TravelMode.WALK
    preference: Preference = Preference.CLEANEST_AIR
    max_extra_minutes: float | None = Field(default=None, ge=0, le=180)
    departure_time: datetime | None = None  # naive values are read as Asia/Kolkata
    explore_detours: bool = True


class SegmentOut(BaseModel):
    path: list[LatLng]
    duration_s: float
    arrival_offset_s: float
    pm25: float | None
    pm10: float | None
    no2_ppb: float | None
    uaqi: int | None
    aqi: int | None = None  # India CPCB scale, hourly estimate
    aqi_category: str | None = None
    dominant_pollutant: str | None = None
    beside_green: float = 0.0  # share of this stretch next to parks or water
    beside_busy_road: float = 0.0
    data_kind: str | None  # "current" | "forecast" | None (no coverage)


class Hotspot(BaseModel):
    location: LatLng
    pm25: float
    minutes: float


class Highlight(BaseModel):
    kind: str  # green | water | road | quiet | industrial | construction
    text: str


class RouteOut(BaseModel):
    id: str
    source: str  # "primary" | "alternative" | "detour" | "green"
    via: str | None = None  # park or lake a green-corridor route was steered through
    labels: list[str]
    duration_s: float
    distance_m: float
    encoded_polyline: str
    exposure_pm25: float | None  # µg/m³·min (relative indicator, not inhaled dose)
    exposure_pm10: float | None
    mean_pm25: float | None
    peak_pm25: float | None
    minutes_above_reference: float | None
    delta_exposure_pct: float | None  # vs fastest; negative = cleaner
    extra_minutes: float  # vs fastest
    within_budget: bool
    coverage: float  # fraction of travel time with AQ data
    distinct_cells: int
    mean_aqi: int | None = None  # time-weighted average along the route
    peak_aqi: int | None = None
    aqi_category: str | None = None
    delta_aqi: int | None = None  # vs fastest; negative = cleaner air
    minutes_green: float = 0.0
    minutes_busy_road: float = 0.0
    highlights: list[Highlight] = []
    segments: list[SegmentOut]
    hotspots: list[Hotspot]


class Comparison(BaseModel):
    meaningful: bool
    basis: str = "exposure"  # "aqi" (cleanest_air) or "exposure"
    recommended_aqi: int | None = None
    fastest_aqi: int | None = None
    reduction_pct: float | None
    extra_minutes: float
    shared_cells_pct: float | None
    message: str


class Usage(BaseModel):
    routes_calls: int = 0
    aq_current_calls: int = 0
    aq_forecast_calls: int = 0
    aq_cache_hits: int = 0
    places_autocomplete_calls: int = 0
    places_details_calls: int = 0
    open_calls: int = 0  # free open-data calls made as a fallback
    routes_source: str | None = None  # "google" | "open" | "mock"
    aq_source: str | None = None
    fallback: bool = False
    estimated_cost_usd: float | None = None


class DataInfo(BaseModel):
    provider: str
    routes_source: str | None = None
    aq_source: str | None = None
    mock: bool
    departure_time: datetime
    computed_at: datetime
    oldest_observation: datetime | None
    uses_forecast: bool
    resolution_note: str


class PlanStatus(BaseModel):
    plan: str  # "anonymous" | "free" | "plus"
    street_level: bool  # this search used street-level (Google) data
    used: int  # street-level searches used this month
    limit: int  # street-level searches included per month
    plus_until: datetime | None = None


class RouteResponse(BaseModel):
    routes: list[RouteOut]
    recommended_id: str
    fastest_id: str
    preference: Preference
    max_extra_minutes: float
    comparison: Comparison
    data: DataInfo
    usage: Usage
    warnings: list[str] = []
    plan: PlanStatus | None = None


class AgentRequest(BaseModel):
    query: str
    origin: LatLng


class AgentResponse(BaseModel):
    verdict: str
    plan: RouteResponse | None = None


class PlaceSuggestion(BaseModel):
    place_id: str
    primary: str
    secondary: str = ""


class PlaceDetails(BaseModel):
    place_id: str
    name: str
    address: str = ""
    location: LatLng
