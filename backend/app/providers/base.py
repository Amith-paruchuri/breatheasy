"""Provider interfaces. Swap Google for OSRM/GraphHopper/CPCB later by implementing these."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from ..geo import Point
from ..models import PlaceDetails, PlaceSuggestion, TravelMode, Usage


class ProviderError(RuntimeError):
    """Upstream API failed in a way the user should hear about."""

    def __init__(self, message: str, status: int = 502, code: str | None = None, suggest_modes: list[str] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.suggest_modes = suggest_modes or []


@dataclass
class RawStep:
    points: list[Point]
    distance_m: float
    duration_s: float  # static (no-traffic) duration from the routing engine


@dataclass
class RawRoute:
    points: list[Point]
    encoded_polyline: str
    distance_m: float
    duration_s: float  # traffic-aware where the engine supports it
    steps: list[RawStep] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)


@dataclass
class AQReading:
    pm25: float | None  # µg/m³
    pm10: float | None  # µg/m³
    no2_ppb: float | None
    uaqi: int | None
    observed_at: datetime
    kind: str  # "current" | "forecast"
    # Gases for the Indian AQI, all µg/m³ except CO in mg/m³
    no2: float | None = None
    o3: float | None = None
    co_mg: float | None = None
    so2: float | None = None


class RouteProvider(Protocol):
    async def compute_routes(
        self,
        origin: Point,
        destination: Point,
        mode: TravelMode,
        *,
        alternatives: bool,
        via: list[Point] | None,
        departure_time: datetime | None,
        usage: Usage,
    ) -> list[RawRoute]: ...


class AirQualityProvider(Protocol):
    async def current(self, lat: float, lng: float, usage: Usage) -> AQReading | None: ...

    async def forecast(
        self, lat: float, lng: float, start: datetime, end: datetime, usage: Usage
    ) -> dict[datetime, AQReading]: ...


class PlacesProvider(Protocol):
    async def autocomplete(
        self, query: str, session: str | None, bias: tuple[float, float, float, float], usage: Usage
    ) -> list[PlaceSuggestion]: ...

    async def details(self, place_id: str, session: str | None, usage: Usage) -> PlaceDetails: ...
