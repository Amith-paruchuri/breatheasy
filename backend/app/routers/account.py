"""Accounts: sign-in, saved places, trip history, export and deletion."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import clear_session, get_db, issue_session, optional_user, require_user
from ..db import SavedPlace, Trip, User, utcnow
from ..models import PlanStatus, Preference, TravelMode
from ..plans import entitlement

router = APIRouter(prefix="/api")


# ---------- schemas ----------
class GoogleCredential(BaseModel):
    credential: str = Field(min_length=20, max_length=5000)


class MeOut(BaseModel):
    id: str
    email: str
    name: str
    picture: str
    created_at: datetime


class MeResponse(BaseModel):
    user: MeOut | None
    accounts_enabled: bool
    plan: PlanStatus | None = None  # present when plans are enabled and someone is signed in


class PlaceIn(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class PlaceOut(PlaceIn):
    id: str
    created_at: datetime


class TripPoint(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class TripIn(BaseModel):
    departure_time: datetime
    mode: TravelMode
    preference: Preference
    origin: TripPoint
    destination: TripPoint
    route_source: Literal["primary", "alternative", "detour", "green"]
    duration_s: float = Field(ge=0, le=86_400)
    distance_m: float = Field(ge=0, le=500_000)
    exposure_pm25: float | None = Field(default=None, ge=0, le=10_000_000)
    fastest_exposure_pm25: float | None = Field(default=None, ge=0, le=10_000_000)
    fastest_duration_s: float | None = Field(default=None, ge=0, le=86_400)
    mean_pm25: float | None = Field(default=None, ge=0, le=5000)
    data_source: str = Field(max_length=32)


class TripOut(BaseModel):
    id: str
    created_at: datetime
    departure_time: datetime
    mode: str
    preference: str
    origin: TripPoint
    destination: TripPoint
    route_source: str
    duration_s: float
    distance_m: float
    exposure_pm25: float | None
    fastest_exposure_pm25: float | None
    fastest_duration_s: float | None
    mean_pm25: float | None
    data_source: str


class Summary(BaseModel):
    trips: int
    minutes_travelled: float
    exposure_total: float
    exposure_avoided: float  # vs the fastest route of each trip, where both are known
    avoided_pct: float | None
    trips_last_30_days: int


def _me(u: User) -> MeOut:
    return MeOut(id=u.id, email=u.email, name=u.name, picture=u.picture, created_at=u.created_at)


def _place(p: SavedPlace) -> PlaceOut:
    return PlaceOut(id=p.id, label=p.label, name=p.name, lat=p.lat, lng=p.lng, created_at=p.created_at)


def _trip(t: Trip) -> TripOut:
    return TripOut(
        id=t.id,
        created_at=t.created_at,
        departure_time=t.departure_time,
        mode=t.mode,
        preference=t.preference,
        origin=TripPoint(name=t.origin_name, lat=t.origin_lat, lng=t.origin_lng),
        destination=TripPoint(name=t.dest_name, lat=t.dest_lat, lng=t.dest_lng),
        route_source=t.route_source,
        duration_s=t.duration_s,
        distance_m=t.distance_m,
        exposure_pm25=t.exposure_pm25,
        fastest_exposure_pm25=t.fastest_exposure_pm25,
        fastest_duration_s=t.fastest_duration_s,
        mean_pm25=t.mean_pm25,
        data_source=t.data_source,
    )


# ---------- auth ----------
@router.post("/auth/google", response_model=MeResponse)
async def sign_in(body: GoogleCredential, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    s = request.app.state.settings
    if not s.accounts_enabled:
        raise HTTPException(404, "Sign-in is not enabled on this server.")
    ident = await request.app.state.token_verifier.verify(body.credential)
    user = (await db.execute(select(User).where(User.google_sub == ident.sub))).scalar_one_or_none()
    if user is None:
        user = User(google_sub=ident.sub, email=ident.email, name=ident.name, picture=ident.picture)
        db.add(user)
    else:
        user.email, user.name, user.picture = ident.email, ident.name, ident.picture
    user.last_login_at = utcnow()
    await db.commit()
    await db.refresh(user)
    issue_session(response, user, s, request.app.state.session_secret)
    return MeResponse(user=_me(user), accounts_enabled=True)


@router.post("/auth/logout", status_code=204)
async def sign_out(request: Request, response: Response):
    clear_session(response, request.app.state.settings)


@router.post("/auth/logout-all", status_code=204)
async def sign_out_everywhere(
    request: Request, response: Response, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)
):
    user.session_version += 1
    await db.commit()
    clear_session(response, request.app.state.settings)


@router.get("/me", response_model=MeResponse)
async def me(request: Request, user: User | None = Depends(optional_user)):
    s = request.app.state.settings
    plan = entitlement(user, s).status if (user and s.plans_enabled) else None
    if plan is not None:
        plan.street_level = plan.used < plan.limit
    return MeResponse(user=_me(user) if user else None, accounts_enabled=s.accounts_enabled, plan=plan)


@router.delete("/me", status_code=204)
async def delete_account(
    request: Request, response: Response, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)
):
    """Deletes the account and every saved place and trip. Irreversible."""
    await db.execute(delete(Trip).where(Trip.user_id == user.id))
    await db.execute(delete(SavedPlace).where(SavedPlace.user_id == user.id))
    await db.delete(user)
    await db.commit()
    clear_session(response, request.app.state.settings)


@router.get("/me/export")
async def export(user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    places = (await db.execute(select(SavedPlace).where(SavedPlace.user_id == user.id))).scalars().all()
    trips = (
        (await db.execute(select(Trip).where(Trip.user_id == user.id).order_by(Trip.created_at.desc()))).scalars().all()
    )
    return {
        "exported_at": utcnow().isoformat(),
        "account": _me(user).model_dump(mode="json"),
        "saved_places": [_place(p).model_dump(mode="json") for p in places],
        "trips": [_trip(t).model_dump(mode="json") for t in trips],
    }


# ---------- saved places ----------
@router.get("/me/places", response_model=list[PlaceOut])
async def list_places(user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(select(SavedPlace).where(SavedPlace.user_id == user.id).order_by(SavedPlace.created_at))
    return [_place(p) for p in rows.scalars()]


@router.post("/me/places", response_model=PlaceOut, status_code=201)
async def add_place(
    body: PlaceIn, request: Request, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)
):
    count = await db.scalar(select(func.count()).select_from(SavedPlace).where(SavedPlace.user_id == user.id))
    if (count or 0) >= request.app.state.settings.max_saved_places:
        raise HTTPException(409, "You've reached the saved-places limit. Remove one first.")
    p = SavedPlace(user_id=user.id, **body.model_dump())
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return _place(p)


@router.delete("/me/places/{place_id}", status_code=204)
async def remove_place(place_id: str, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    res = await db.execute(delete(SavedPlace).where(SavedPlace.id == place_id, SavedPlace.user_id == user.id))
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "Place not found.")


# ---------- trips ----------
@router.get("/me/trips", response_model=list[TripOut])
async def list_trips(
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    before: datetime | None = None,
):
    q = select(Trip).where(Trip.user_id == user.id)
    if before:
        q = q.where(Trip.created_at < before)
    rows = await db.execute(q.order_by(Trip.created_at.desc()).limit(limit))
    return [_trip(t) for t in rows.scalars()]


@router.post("/me/trips", response_model=TripOut, status_code=201)
async def add_trip(body: TripIn, request: Request, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    since = utcnow() - timedelta(days=1)
    recent = await db.scalar(
        select(func.count()).select_from(Trip).where(Trip.user_id == user.id, Trip.created_at >= since)
    )
    if (recent or 0) >= request.app.state.settings.max_trips_per_day:
        raise HTTPException(429, "Daily trip limit reached.")
    dep = body.departure_time if body.departure_time.tzinfo else body.departure_time.replace(tzinfo=timezone.utc)
    t = Trip(
        user_id=user.id,
        departure_time=dep,
        mode=body.mode.value,
        preference=body.preference.value,
        origin_name=body.origin.name,
        origin_lat=body.origin.lat,
        origin_lng=body.origin.lng,
        dest_name=body.destination.name,
        dest_lat=body.destination.lat,
        dest_lng=body.destination.lng,
        route_source=body.route_source,
        duration_s=body.duration_s,
        distance_m=body.distance_m,
        exposure_pm25=body.exposure_pm25,
        fastest_exposure_pm25=body.fastest_exposure_pm25,
        fastest_duration_s=body.fastest_duration_s,
        mean_pm25=body.mean_pm25,
        data_source=body.data_source,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _trip(t)


@router.delete("/me/trips/{trip_id}", status_code=204)
async def remove_trip(trip_id: str, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    res = await db.execute(delete(Trip).where(Trip.id == trip_id, Trip.user_id == user.id))
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "Trip not found.")


@router.delete("/me/trips", status_code=204)
async def clear_trips(user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Trip).where(Trip.user_id == user.id))
    await db.commit()


@router.get("/me/summary", response_model=Summary)
async def summary(user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    trips = (await db.execute(select(Trip).where(Trip.user_id == user.id))).scalars().all()
    month_ago = utcnow() - timedelta(days=30)
    total_exp = sum(t.exposure_pm25 or 0 for t in trips)
    paired = [t for t in trips if t.exposure_pm25 is not None and t.fastest_exposure_pm25]
    avoided = sum(t.fastest_exposure_pm25 - t.exposure_pm25 for t in paired)
    base = sum(t.fastest_exposure_pm25 for t in paired)

    def aware(d: datetime) -> datetime:  # SQLite returns naive datetimes
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

    return Summary(
        trips=len(trips),
        minutes_travelled=round(sum(t.duration_s for t in trips) / 60, 1),
        exposure_total=round(total_exp, 1),
        exposure_avoided=round(avoided, 1),
        avoided_pct=round(avoided / base * 100, 1) if base else None,
        trips_last_30_days=sum(1 for t in trips if aware(t.created_at) >= month_ago),
    )


async def purge_old_trips(db: AsyncSession, retention_days: int) -> int:
    cutoff = utcnow() - timedelta(days=retention_days)
    res = await db.execute(delete(Trip).where(Trip.created_at < cutoff))
    await db.commit()
    return res.rowcount or 0
