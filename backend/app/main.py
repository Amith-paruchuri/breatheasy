"""FastAPI application: API + (in production) the built frontend, one origin."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import __version__
from .auth import TokenVerifier, get_db, optional_user
from .budget import SpendGuard
from .config import get_settings
from .db import Database, User
from .environment import EnvironmentLayer
from .migrate import run_migrations
from .plans import consume, entitlement
from .models import PlaceDetails, PlaceSuggestion, RouteRequest, RouteResponse, TravelMode, Usage
from .providers import ProviderError, build_providers
from .routers import account, billing
from .services.airquality import AQCache, AQService
from .services.planner import plan_routes
from .web import RateLimiter, WebMiddleware, client_ip, mount_frontend, setup_logging

log = logging.getLogger("breatheasy")


class StartupError(RuntimeError):
    pass


async def _purge_loop(app: FastAPI) -> None:
    while True:
        try:
            async with app.state.db.sessions() as db:
                n = await account.purge_old_trips(db, app.state.settings.trip_retention_days)
            if n:
                log.info("purged %d trips older than %d days", n, app.state.settings.trip_retention_days)
        except Exception:  # never let housekeeping kill the app
            log.exception("trip purge failed")
        await asyncio.sleep(6 * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging(s)
    problems = s.production_problems()
    if problems:
        for p in problems:
            log.error("config: %s", p)
        raise StartupError("Unsafe production configuration: " + " ".join(problems))

    app.state.settings = s
    app.state.session_secret = s.session_secret or secrets.token_hex(32)
    if not s.session_secret:
        log.warning("SESSION_SECRET not set: using a random one, so sign-ins reset on restart (fine for dev)")
    app.state.db = Database(s.database_url)
    if s.run_migrations_on_startup:
        await run_migrations(app.state.db.engine)
    app.state.token_verifier = TokenVerifier(s.google_oauth_client_id)
    app.state.providers = build_providers(s)
    env_path = s.env_layer_path or str(Path(__file__).parent / "data" / "environment.json.gz")
    app.state.env = await asyncio.to_thread(EnvironmentLayer.load, env_path)
    app.state.aq = AQService(app.state.providers.air, s, AQCache(s.aq_cache_ttl_s))
    app.state.spend = SpendGuard(app.state.db.engine, s)
    app.state.route_limiter = RateLimiter(s.route_requests_per_minute)
    app.state.place_limiter = RateLimiter(s.place_requests_per_minute)
    purge = asyncio.create_task(_purge_loop(app))
    log.info("Breatheasy %s started (env=%s, provider=%s, accounts=%s)", __version__, s.env, s.provider, s.accounts_enabled)
    try:
        yield
    finally:
        purge.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await purge
        await app.state.providers.aclose()
        await app.state.db.dispose()


settings_at_import = get_settings()
app = FastAPI(
    title="Breatheasy API",
    version=__version__,
    lifespan=lifespan,
    docs_url=None if settings_at_import.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings_at_import.is_production else "/openapi.json",
)
app.add_middleware(WebMiddleware, settings=settings_at_import)
if not settings_at_import.is_production:
    # Dev only: Vite runs on another port. Production serves app + API from one origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings_at_import.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-Requested-With"],
    )


@app.exception_handler(ProviderError)
async def provider_error(_: Request, exc: ProviderError):
    status = exc.status if 400 <= exc.status < 600 else 502
    if (status >= 500 or status == 429) and not exc.code:
        log.warning("provider error: %s", exc)
        # Upstream detail (Google error text) stays in our logs, not in the browser.
        msg = "Route and air-quality services are busy right now. Try again in a minute."
        return JSONResponse(status_code=503 if status != 429 else 429, content={"detail": msg, "code": "busy"})
    body: dict = {"detail": str(exc)}
    if exc.code:
        body["code"] = exc.code
    if exc.suggest_modes:
        body["suggest_modes"] = exc.suggest_modes
    return JSONResponse(status_code=status, content=body)


# ---------- health ----------
@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}


@app.get("/readyz", include_in_schema=False)
async def readyz(request: Request):
    try:
        async with request.app.state.db.engine.connect() as c:
            await c.execute(text("SELECT 1"))
    except Exception:
        log.exception("readiness: database unreachable")
        return JSONResponse({"ok": False, "database": "unreachable"}, status_code=503)
    return {"ok": True}


@app.get("/api/health")
async def health(request: Request):
    s = request.app.state.settings
    return {"ok": True, "version": __version__, "provider": s.provider, "mock": s.is_mock}


@app.get("/api/config")
async def config(request: Request):
    """Public runtime config. Everything here is safe to expose to browsers."""
    s = request.app.state.settings
    return {
        "provider": s.provider,
        "mock": s.is_mock,
        "data_note": request.app.state.providers.data_note,
        "region": {
            "name": s.region_name,
            "south": s.region_south,
            "west": s.region_west,
            "north": s.region_north,
            "east": s.region_east,
        },
        "modes": [m.value for m in TravelMode],
        "default_max_extra_minutes": s.default_max_extra_minutes,
        "meaningful_diff_pct": s.meaningful_diff_pct,
        "pm25_reference_ugm3": s.pm25_reference_ugm3,
        "cleanest_air_default_extra_minutes": s.cleanest_air_default_extra_minutes,
        "street_context": not request.app.state.env.empty,
        "maps_browser_key": s.google_maps_browser_key,
        "map_id": s.google_map_id,
        "google_oauth_client_id": s.google_oauth_client_id,
        "accounts_enabled": s.accounts_enabled,
        "plans": {
            "enabled": s.plans_enabled,
            "payments": s.payments_enabled,
            "free_street_searches": s.free_street_searches,
            "plus_street_searches": s.plus_street_searches,
            "monthly_inr": s.plus_price_monthly_inr if s.razorpay_plan_monthly else None,
            "yearly_inr": s.plus_price_yearly_inr if s.razorpay_plan_yearly else None,
            "razorpay_key_id": s.razorpay_key_id if s.payments_enabled else "",
        },
        "operator_name": s.operator_name,
        "contact_email": s.public_contact_email,
        "version": __version__,
    }


# ---------- places + routes ----------
@app.get("/api/places/autocomplete", response_model=list[PlaceSuggestion])
async def autocomplete(
    request: Request, q: str = Query(min_length=2, max_length=120), session: str | None = Query(None, max_length=64)
):
    if not request.app.state.place_limiter.check(client_ip(request)):
        raise HTTPException(429, "Too many searches. Slow down a little.")
    s = request.app.state.settings
    bias = (s.region_south, s.region_west, s.region_north, s.region_east)
    return await request.app.state.providers.places.autocomplete(q, session, bias, Usage())


@app.get("/api/places/{place_id}", response_model=PlaceDetails)
async def place_details(request: Request, place_id: str, session: str | None = Query(None, max_length=64)):
    if len(place_id) > 400:
        raise HTTPException(400, "Invalid place.")
    if not request.app.state.place_limiter.check(client_ip(request)):
        raise HTTPException(429, "Too many searches. Slow down a little.")
    usage = Usage()
    out = await request.app.state.providers.places.details(place_id, session, usage)
    await request.app.state.spend.record(usage, None, search=False)
    return out


@app.post("/api/routes", response_model=RouteResponse)
async def routes(
    request: Request,
    body: RouteRequest,
    user: User | None = Depends(optional_user),
    db: AsyncSession = Depends(get_db),
):
    if not request.app.state.route_limiter.check(client_ip(request)):
        raise HTTPException(429, "Too many route requests. Try again in a minute.")
    s = request.app.state.settings
    guard = request.app.state.spend
    ent = entitlement(user, s)
    over = await guard.over_budget()
    resp = await plan_routes(
        body,
        request.app.state.providers,
        request.app.state.aq,
        s,
        request.app.state.env,
        force_open=over or not ent.street,
        open_reason=None if over else ent.reason,
    )
    await guard.record(resp.usage, body.mode)
    if ent.status is not None:
        # Street-level = this search really used the paid provider (not open data).
        street = ent.street and not over and resp.usage.aq_source != "open"
        ent.status.street_level = street
        if street and user is not None:
            consume(user, ent.status)
            await db.commit()
        resp.plan = ent.status
    return resp


app.include_router(account.router)
app.include_router(billing.router)

# Must be last: catch-all route for the single-page app.
mount_frontend(app, settings_at_import.static_dir)
