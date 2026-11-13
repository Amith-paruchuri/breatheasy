"""Runtime configuration, loaded from environment variables or backend/.env."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Environment -----------------------------------------------------
    env: Literal["development", "production"] = "development"
    log_level: str = "INFO"
    # Built frontend (Vite dist). When the folder exists the API also serves the app,
    # so production is ONE origin: no CORS, first-party cookies.
    static_dir: str = "static"

    # --- Database --------------------------------------------------------
    # Dev/tests: SQLite file. Production: Postgres, e.g.
    #   postgresql+asyncpg://USER:PASS@/DB?host=/cloudsql/PROJECT:REGION:INSTANCE
    database_url: str = "sqlite+aiosqlite:///./data/breatheasy.db"
    run_migrations_on_startup: bool = True

    # --- Accounts (Google sign-in) ---------------------------------------
    google_oauth_client_id: str = ""  # "Web application" OAuth client ID; empty = sign-in disabled
    session_secret: str = ""  # >= 32 random chars in production (openssl rand -hex 32)
    session_days: int = 30
    trip_retention_days: int = 365  # older trips are deleted automatically
    max_saved_places: int = 50
    max_trips_per_day: int = 200

    # --- Operator (shown on the privacy policy and terms) ----------------
    operator_name: str = "Dr Amith Paruchuri"
    # Contact for privacy/grievance requests. Blank: taken from USER_AGENT's email.
    contact_email: str = ""

    # --- Public browser config (served to the frontend at runtime) -------
    # Restrict this key to Maps JavaScript API + your domain (HTTP referrers).
    google_maps_browser_key: str = ""
    google_map_id: str = ""

    # --- Security headers ------------------------------------------------
    # "report-only" first: check the browser console for CSP reports, then "enforce".
    csp_mode: Literal["enforce", "report-only", "off"] = "report-only"

    # --- Providers -------------------------------------------------------
    # "open"   real data, no key: OpenStreetMap routing (FOSSGIS OSRM), Open-Meteo
    #          air quality (CAMS model, coarse grid), Photon place search.
    # "google" Routes API + Air Quality API (~500 m grid) + Places API (New). Needs a key.
    # "mock"   synthetic routes and pollution for offline development and tests.
    provider: Literal["open", "google", "mock"] = "open"
    # With PROVIDER=google: if Google fails (quota, key, outage), serve open data instead.
    provider_fallback: bool = True
    fallback_cooldown_s: int = 60  # after a Google outage/quota error, skip Google this long
    google_maps_server_key: str = ""  # server-side key: restrict by IP + API list
    http_timeout_s: float = 15.0
    osrm_base_url: str = "https://routing.openstreetmap.de"
    open_meteo_aq_url: str = "https://air-quality-api.open-meteo.com/v1/air-quality"
    photon_url: str = "https://photon.komoot.io/api/"
    # Public OSM services ask for an identifying User-Agent. Put your email in it.
    user_agent: str = "Breatheasy/0.1 (prototype; contact: set USER_AGENT in .env)"
    max_concurrent_aq_calls: int = 24

    # --- Region (Delhi-NCR pilot) ----------------------------------------
    # Service area: routes and air data work anywhere in it (India).
    service_name: str = "India"
    service_south: float = 6.5
    service_west: float = 68.0
    service_north: float = 37.2
    service_east: float = 97.5
    # Home region: where the map opens and place search leans first. Street-level
    # context (parks, lakes, main roads) is built for this region.
    region_name: str = "Delhi-NCR"
    region_south: float = 28.20
    region_west: float = 76.80
    region_north: float = 28.95
    region_east: float = 77.75

    # --- Route sampling and air-quality lookup ---------------------------
    # Google AQ data is ~500 m x 500 m. Sampling much finer than that only
    # multiplies API calls without adding information.
    sample_spacing_m: float = 400.0
    aq_cell_deg: float = 0.0045  # ~500 m in latitude; used for de-duplication + cache
    aq_cache_ttl_s: int = 1800  # verify against current Google Maps Platform terms
    forecast_horizon_h: int = 96
    # Parts of the trip reached within this many minutes use current conditions
    # (one cheap lookup) rather than the hourly forecast.
    current_window_min: int = 120

    # --- Candidate generation --------------------------------------------
    max_candidates: int = 8
    detour_count: int = 2  # 0, 2 or 4 extra waypoint-detour routes per request
    detour_offset_frac: float = 0.18  # perpendicular offset as fraction of O-D distance
    detour_offset_min_m: float = 350.0
    detour_offset_max_m: float = 3000.0
    duplicate_overlap: float = 0.85  # drop a candidate sharing >85% of geometry
    detour_max_trip_km: float = 20.0  # longer trips skip detour exploration (2 fewer Routes calls)

    # --- Speed and cost guards (every search must answer in a few seconds) -
    max_segments_per_route: int = 40  # long routes are sampled more coarsely
    max_aq_cells: int = 75  # distinct air-quality lookups per search; grid coarsens beyond this
    # Cars and two-wheelers cross a 500 m cell in well under a minute, so they read the
    # air on a ~1 km grid (scale 2): about half the Air Quality calls, same ranking.
    aq_vehicle_scale: int = 2
    aq_deadline_s: float = 10.0  # Google AQ slower than this -> open data for this search
    # Straight-line trip limits per mode; beyond these the app suggests another mode.
    max_trip_km_walk: float = 15.0
    max_trip_km_bicycle: float = 40.0
    max_trip_km_two_wheeler: float = 150.0
    max_trip_km_drive: float = 150.0
    # Re-ranking the same trip (changing preference or time budget) reuses the
    # candidates for this many seconds instead of re-calling the Routes API.
    # Keep short and verify against current Google Maps Platform terms.
    route_cache_ttl_s: int = 120

    # --- Ranking ---------------------------------------------------------
    default_max_extra_minutes: float = 10.0
    meaningful_diff_pct: float = 10.0  # below this, routes are treated as equivalent
    meaningful_pm25_ugm3: float = 5.0  # cleanest-air mode: smaller PM2.5 gains count as "about the same"
    cleanest_air_default_extra_minutes: float = 45.0  # default time budget when hunting for the cleanest air
    green_detours: int = 3  # extra candidate routes through nearby parks / lakes
    green_detour_min_area_m2: float = 30_000.0

    # --- Street-level adjustment (needs the OpenStreetMap environment layer) ---
    # Modelled AQ grids can't see the street. Near-road studies typically find
    # higher particle levels beside busy roads, and modestly lower beside large
    # green space; these conservative factors nudge each stretch accordingly.
    # Set both to 0 to use the model values unchanged.
    env_layer_path: str = ""  # default: app/data/environment.json.gz
    street_adjust_busy_road: float = 0.15
    street_adjust_green: float = 0.05
    balanced_pct_per_min: float = 1.5  # balanced mode: 1 extra minute must buy >=1.5% less exposure
    pm25_reference_ugm3: float = 60.0  # India NAAQS 24-h PM2.5 level, shown for reference only

    # --- Agent -----------------------------------------------------------
    agent_llm: Literal["rules", "vertex"] = "rules"
    vertex_project: str = ""
    vertex_location: str = "us-central1"

    # --- Cost tracking -----------------------------------------------------
    # Google Maps Platform India price list, USD per 1,000 billable calls, for usage
    # above the free monthly allowance and below 5 million calls (checked Nov 2026:
    # developers.google.com/maps/billing-and-pricing/pricing-india). Used for the
    # cost shown per search and for the daily spending cap below. Update if Google
    # changes its prices. Free allowances are ignored here, so estimates run high.
    price_routes_per_1000_usd: float | None = 1.50  # Compute Routes Essentials (walk, cycle)
    price_routes_pro_per_1000_usd: float = 3.00  # TRAFFIC_AWARE (car)
    price_routes_enterprise_per_1000_usd: float = 4.50  # two-wheeler routing
    price_aq_per_1000_usd: float | None = 0.50
    price_places_autocomplete_per_1000_usd: float | None = 0.85
    price_places_details_per_1000_usd: float | None = 1.50  # Place Details Essentials
    # Spending cap: once today's estimated Google spend (India time) passes this, the
    # app answers from free open data until midnight instead of calling Google.
    # 0 turns the cap off. 10 USD/day caps the Google bill at roughly 300 USD/month.
    google_daily_budget_usd: float = 10.0
    # Validation against CPCB stations (data.gov.in) and the scheduler token that triggers it
    datagov_api_key: str = ""
    openaq_api_key: str = ""  # free key from explore.openaq.org; hourly CPCB readings
    validation_token: str = ""
    validation_stations: int = 60

    # --- Plans and payments ----------------------------------------------
    # Off by default: everyone gets street-level (Google) data, as before. On: signed-out
    # visitors get open data, signed-in Free users get FREE_STREET_SEARCHES a month and
    # Plus subscribers PLUS_STREET_SEARCHES (fair use); past that, open data.
    plans_enabled: bool = False
    free_street_searches: int = 5
    plus_street_searches: int = 100
    plus_price_monthly_inr: int = 149
    plus_price_yearly_inr: int = 1199
    # Razorpay (payments stay off until all of these are set). Create two plans in the
    # Razorpay dashboard (monthly and yearly) and paste their IDs here.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_plan_monthly: str = ""
    razorpay_plan_yearly: str = ""
    razorpay_api_url: str = "https://api.razorpay.com/v1"

    # --- Safety rails ----------------------------------------------------
    route_requests_per_minute: int = 20  # per client IP, protects your billing account
    place_requests_per_minute: int = 120  # autocomplete is called while typing
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- Research logging (opt-in) ---------------------------------------
    # Writes one JSON line per route request with coordinates rounded to ~110 m.
    log_journeys: bool = False
    journey_log_path: str = "data/journeys.jsonl"

    @field_validator(
        "price_routes_per_1000_usd",
        "price_aq_per_1000_usd",
        "price_places_autocomplete_per_1000_usd",
        "price_places_details_per_1000_usd",
        mode="before",
    )
    @classmethod
    def _blank_is_none(cls, v):
        # `PRICE_X=` left blank in .env means "unknown", not an error
        return None if isinstance(v, str) and not v.strip() else v

    @property
    def is_mock(self) -> bool:
        return self.provider == "mock"

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def accounts_enabled(self) -> bool:
        return bool(self.google_oauth_client_id)

    @property
    def payments_enabled(self) -> bool:
        return bool(
            self.plans_enabled
            and self.razorpay_key_id
            and self.razorpay_key_secret
            and self.razorpay_webhook_secret
            and (self.razorpay_plan_monthly or self.razorpay_plan_yearly)
        )

    @property
    def public_contact_email(self) -> str:
        if self.contact_email:
            return self.contact_email
        m = re.search(r"[\w.-][\w.+-]*@[\w-]+\.[\w.]+", self.user_agent.replace("+", " "))
        return m.group(0) if m else ""

    def production_problems(self) -> list[str]:
        """Settings that make a production deploy unsafe. Startup refuses to run with any."""
        out: list[str] = []
        if not self.is_production:
            return out
        if len(self.session_secret) < 32:
            out.append("SESSION_SECRET must be at least 32 characters (openssl rand -hex 32).")
        if self.database_url.startswith("sqlite"):
            out.append("DATABASE_URL points at SQLite; use Postgres in production (Cloud Run disks are ephemeral).")
        if self.provider == "mock":
            out.append("PROVIDER=mock serves synthetic data.")
        if self.provider == "google" and not self.google_maps_server_key:
            out.append("PROVIDER=google needs GOOGLE_MAPS_SERVER_KEY.")
        if self.provider == "google" and not self.google_maps_browser_key:
            out.append("PROVIDER=google needs GOOGLE_MAPS_BROWSER_KEY: Google route data must be shown on a Google map.")
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
