"""Breatheasy Plus subscriptions through Razorpay.

Flow: the app asks /api/billing/subscribe for a Razorpay subscription, opens
Razorpay Checkout with it, then posts the payment's signature to
/api/billing/verify, which turns Plus on. Razorpay's webhook keeps it on with every
renewal (subscription.charged) and lets it lapse at the end of the paid period after a
cancellation or failed renewals. Everything is off until PLANS_ENABLED and all
RAZORPAY_* settings are present.

Signatures (Razorpay docs): checkout = HMAC-SHA256(payment_id + "|" + subscription_id,
key_secret); webhook = HMAC-SHA256(raw body, webhook secret), hex, in X-Razorpay-Signature.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_db, require_user
from ..config import Settings
from ..db import User
from ..plans import is_plus

log = logging.getLogger("breatheasy.billing")
router = APIRouter(prefix="/api/billing")

GRACE = timedelta(days=2)  # renewals can land a little after the period ends
PERIOD = {"monthly": timedelta(days=31), "yearly": timedelta(days=366)}


class SubscribeIn(BaseModel):
    period: Literal["monthly", "yearly"] = "monthly"


class SubscribeOut(BaseModel):
    subscription_id: str
    key_id: str
    amount_inr: int
    name: str
    email: str


class VerifyIn(BaseModel):
    razorpay_payment_id: str = Field(min_length=4, max_length=64)
    razorpay_subscription_id: str = Field(min_length=4, max_length=64)
    razorpay_signature: str = Field(min_length=16, max_length=256)
    period: Literal["monthly", "yearly"] = "monthly"


class PlanOut(BaseModel):
    plan: str
    plus_until: datetime | None


def _settings(request: Request) -> Settings:
    s: Settings = request.app.state.settings
    if not s.payments_enabled:
        raise HTTPException(404, "Payments aren't switched on yet.")
    return s


def _hmac(secret: str, msg: bytes) -> str:
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _extend(user: User, until: datetime) -> None:
    current = _aware(user.plus_until)
    user.plan = "plus"
    user.plus_until = max(current, until) if current else until


async def _razorpay(s: Settings, method: str, path: str, body: dict | None = None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.request(
                method, f"{s.razorpay_api_url}{path}", json=body, auth=(s.razorpay_key_id, s.razorpay_key_secret)
            )
    except httpx.HTTPError as exc:
        log.warning("razorpay unreachable: %s", exc)
        raise HTTPException(503, "Payments are unavailable right now. Please try again in a minute.") from exc
    if r.status_code >= 400:
        log.warning("razorpay %s %s -> %s %s", method, path, r.status_code, r.text[:300])
        raise HTTPException(502, "The payment provider couldn't start this subscription. Please try again.")
    return r.json()


@router.post("/subscribe", response_model=SubscribeOut)
async def subscribe(
    body: SubscribeIn, request: Request, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)
):
    s = _settings(request)
    plan_id = s.razorpay_plan_monthly if body.period == "monthly" else s.razorpay_plan_yearly
    if not plan_id:
        raise HTTPException(400, f"The {body.period} plan isn't available.")
    sub = await _razorpay(
        s,
        "POST",
        "/subscriptions",
        {
            "plan_id": plan_id,
            "total_count": 120 if body.period == "monthly" else 10,  # renews until cancelled
            "customer_notify": 1,
            "notes": {"user_id": user.id, "period": body.period},
        },
    )
    user.razorpay_subscription_id = sub["id"]
    await db.commit()
    amount = s.plus_price_monthly_inr if body.period == "monthly" else s.plus_price_yearly_inr
    return SubscribeOut(subscription_id=sub["id"], key_id=s.razorpay_key_id, amount_inr=amount, name=user.name, email=user.email)


@router.post("/verify", response_model=PlanOut)
async def verify(body: VerifyIn, request: Request, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    s = _settings(request)
    if body.razorpay_subscription_id != user.razorpay_subscription_id:
        raise HTTPException(400, "This payment doesn't match your subscription.")
    expected = _hmac(s.razorpay_key_secret, f"{body.razorpay_payment_id}|{body.razorpay_subscription_id}".encode())
    if not hmac.compare_digest(expected, body.razorpay_signature):
        raise HTTPException(400, "The payment couldn't be verified.")
    _extend(user, datetime.now(timezone.utc) + PERIOD[body.period])
    await db.commit()
    log.info("plus activated for user %s (%s)", user.id, body.period)
    return PlanOut(plan=user.plan, plus_until=_aware(user.plus_until))


@router.post("/cancel", response_model=PlanOut)
async def cancel(request: Request, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    """Stops renewals; Plus stays on until the end of the period already paid for."""
    s = _settings(request)
    if not user.razorpay_subscription_id:
        raise HTTPException(400, "You don't have a subscription to cancel.")
    await _razorpay(s, "POST", f"/subscriptions/{user.razorpay_subscription_id}/cancel", {"cancel_at_cycle_end": 1})
    return PlanOut(plan=user.plan if is_plus(user) else "free", plus_until=_aware(user.plus_until))


@router.post("/webhook", status_code=200)
async def webhook(request: Request, db: AsyncSession = Depends(get_db)):
    s = _settings(request)
    raw = await request.body()
    sig = request.headers.get("x-razorpay-signature", "")
    if not sig or not hmac.compare_digest(_hmac(s.razorpay_webhook_secret, raw), sig):
        raise HTTPException(400, "Bad signature.")
    try:
        event = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(400, "Bad payload.") from exc
    kind = event.get("event", "")
    sub = (event.get("payload", {}).get("subscription", {}) or {}).get("entity", {}) or {}
    sub_id = sub.get("id")
    user_id = (sub.get("notes") or {}).get("user_id")
    user = None
    if user_id:
        user = await db.get(User, user_id)
    if user is None and sub_id:
        user = (await db.execute(select(User).where(User.razorpay_subscription_id == sub_id))).scalar_one_or_none()
    if user is None:
        log.info("razorpay webhook %s for unknown subscription %s", kind, sub_id)
        return {"ok": True}
    if kind in ("subscription.activated", "subscription.charged", "subscription.resumed"):
        end = sub.get("current_end")
        if end:
            _extend(user, datetime.fromtimestamp(int(end), tz=timezone.utc) + GRACE)
            if sub_id:
                user.razorpay_subscription_id = sub_id
            await db.commit()
    # cancelled / halted / completed: nothing to do, Plus lapses when plus_until passes.
    log.info("razorpay webhook %s for user %s", kind, user.id)
    return {"ok": True}
