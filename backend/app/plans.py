"""Free / Plus plans: who gets street-level (Google) data on a search.

With PLANS_ENABLED off (the default) every search may use Google, as before.
With it on: signed-out visitors use open data; signed-in users get a monthly
allowance of street-level searches (Free: FREE_STREET_SEARCHES, Plus:
PLUS_STREET_SEARCHES); past it, open data until the next month (India time).
Only searches that actually used Google data count against the allowance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import Settings
from .db import User
from .models import PlanStatus

IST = timezone(timedelta(hours=5, minutes=30))


def month_key(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(IST).strftime("%Y-%m")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes


def is_plus(user: User | None, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    until = _aware(user.plus_until) if user else None
    return bool(user and user.plan == "plus" and until and until > now)


def used_this_month(user: User, now: datetime | None = None) -> int:
    return user.street_used if user.street_month == month_key(now) else 0


@dataclass
class Entitlement:
    street: bool
    reason: str | None  # why this search uses open data
    status: PlanStatus | None


def entitlement(user: User | None, s: Settings, now: datetime | None = None) -> Entitlement:
    if not s.plans_enabled:
        return Entitlement(True, None, None)
    if user is None:
        return Entitlement(
            False,
            "You're seeing open-data routes. Sign in for free street-level air data on "
            f"{s.free_street_searches} searches a month.",
            PlanStatus(plan="anonymous", street_level=False, used=0, limit=0),
        )
    plus = is_plus(user, now)
    limit = s.plus_street_searches if plus else s.free_street_searches
    used = used_this_month(user, now)
    status = PlanStatus(
        plan="plus" if plus else "free", street_level=used < limit, used=used, limit=limit,
        plus_until=_aware(user.plus_until) if plus else None,
    )
    if used < limit:
        return Entitlement(True, None, status)
    reason = (
        f"You've used this month's {limit} street-level searches, so this one uses open data."
        if plus
        else f"You've used your {limit} free street-level searches this month, so this one uses open data. "
        "Breatheasy Plus includes street-level air on every trip."
    )
    return Entitlement(False, reason, status)


def consume(user: User, status: PlanStatus, now: datetime | None = None) -> None:
    """Count one street-level search (the caller commits)."""
    key = month_key(now)
    if user.street_month != key:
        user.street_month, user.street_used = key, 0
    user.street_used += 1
    status.used = user.street_used
