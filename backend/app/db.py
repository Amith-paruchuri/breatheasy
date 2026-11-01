"""Database engine, session factory and ORM models.

SQLite for development and tests, Postgres in production. Schema changes go
through Alembic migrations in `migrations/`; never edit tables by hand.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    event,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    picture: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    # Bumped by "sign out everywhere" and account deletion; old sessions stop working.
    session_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    # Plans: "free" or "plus"; Plus is active while plus_until is in the future.
    plan: Mapped[str] = mapped_column(String(16), default="free", server_default="free", nullable=False)
    plus_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(64))
    # Street-level searches used in street_month ("YYYY-MM", India time).
    street_month: Mapped[str] = mapped_column(String(7), default="", server_default="", nullable=False)
    street_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    places: Mapped[list[SavedPlace]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    trips: Mapped[list[Trip]] = relationship(back_populates="user", cascade="all, delete-orphan", passive_deletes=True)


class SavedPlace(Base):
    __tablename__ = "saved_places"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(String(40), nullable=False)  # "Home", "Work", "Gym"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="places")

    __table_args__ = (Index("ix_saved_places_user", "user_id"),)


class Trip(Base):
    """A route the user chose to take. Kept as a personal exposure log."""

    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    departure_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    preference: Mapped[str] = mapped_column(String(16), nullable=False)
    origin_name: Mapped[str] = mapped_column(String(200), nullable=False)
    origin_lat: Mapped[float] = mapped_column(Float, nullable=False)
    origin_lng: Mapped[float] = mapped_column(Float, nullable=False)
    dest_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dest_lat: Mapped[float] = mapped_column(Float, nullable=False)
    dest_lng: Mapped[float] = mapped_column(Float, nullable=False)
    route_source: Mapped[str] = mapped_column(String(16), nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    exposure_pm25: Mapped[float | None] = mapped_column(Float)
    fastest_exposure_pm25: Mapped[float | None] = mapped_column(Float)
    fastest_duration_s: Mapped[float | None] = mapped_column(Float)
    mean_pm25: Mapped[float | None] = mapped_column(Float)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False)

    user: Mapped[User] = relationship(back_populates="trips")

    __table_args__ = (Index("ix_trips_user_created", "user_id", "created_at"),)


def make_engine(url: str) -> AsyncEngine:
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_async_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine.sync_engine, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite ignores ON DELETE CASCADE unless asked
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return engine
    # Cloud Run scales instances; keep each one's pool small so Cloud SQL isn't exhausted.
    return create_async_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True, pool_recycle=1800)


class Database:
    def __init__(self, url: str):
        self.engine = make_engine(url)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as s:
            yield s

    async def dispose(self) -> None:
        await self.engine.dispose()
