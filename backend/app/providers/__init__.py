"""Provider factory."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from .base import AirQualityProvider, PlacesProvider, ProviderError, RouteProvider

DATA_NOTES = {
    "google": "Google Air Quality model on a ~500 m grid, not street-level measurements.",
    "open": (
        "Open-Meteo / Copernicus CAMS model on a coarse (~40 km) grid over India. Good for how air "
        "changes through the day; weak at telling nearby streets apart, so route differences are indicative."
    ),
    "mock": "SYNTHETIC demo data, not real air quality.",
}


@dataclass
class Providers:
    routes: RouteProvider
    air: AirQualityProvider
    places: PlacesProvider
    name: str
    _client: object | None = None
    free: bool = False

    @property
    def data_note(self) -> str:
        return DATA_NOTES[self.name]

    def note_for(self, source: str | None) -> str:
        return DATA_NOTES.get(source or self.name, DATA_NOTES[self.name])

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()  # type: ignore[attr-defined]


def build_providers(settings: Settings) -> Providers:
    def open_parts(http):
        from .open import OpenAirQuality, OpenPlaces, OpenRoutes

        return (
            OpenRoutes(http, settings.osrm_base_url),
            OpenAirQuality(http, settings.open_meteo_aq_url),
            OpenPlaces(http, settings.photon_url),
        )

    if settings.provider == "google":
        import httpx

        from .google import GoogleAirQuality, GoogleClient, GooglePlaces, GoogleRoutes

        client = GoogleClient(settings.google_maps_server_key, settings.http_timeout_s)
        g_routes, g_air, g_places = GoogleRoutes(client), GoogleAirQuality(client), GooglePlaces(client)
        if not settings.provider_fallback:
            return Providers(g_routes, g_air, g_places, "google", _Closer(client.http))

        from .fallback import Breaker, FallbackAir, FallbackPlaces, FallbackRoutes

        http = httpx.AsyncClient(timeout=settings.http_timeout_s, headers={"User-Agent": settings.user_agent})
        o_routes, o_air, o_places = open_parts(http)
        breaker = Breaker(settings.fallback_cooldown_s)
        return Providers(
            FallbackRoutes(g_routes, o_routes, breaker),
            FallbackAir(g_air, o_air, breaker),
            FallbackPlaces(g_places, o_places, breaker),
            "google",
            _Closer(client.http, http),
        )

    if settings.provider == "open":
        import httpx

        http = httpx.AsyncClient(timeout=settings.http_timeout_s, headers={"User-Agent": settings.user_agent})
        return Providers(*open_parts(http), "open", http, free=True)

    from .mock import MockAirQuality, MockPlaces, MockRoutes

    return Providers(MockRoutes(), MockAirQuality(), MockPlaces(), "mock", free=True)


class _Closer:
    def __init__(self, *clients):
        self.clients = clients

    async def aclose(self) -> None:
        for c in self.clients:
            await c.aclose()


__all__ = ["Providers", "ProviderError", "build_providers"]
