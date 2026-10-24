"""Google sign-in and session cookies.

Flow: the browser gets an ID token from Google Identity Services and posts it to
/api/auth/google. We verify it against Google's keys and our OAuth client ID,
upsert the user, and set our own signed session cookie (HttpOnly, Secure in
production, SameSite=Lax). The Google token itself is never stored.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .db import User

ALGO = "HS256"


@dataclass
class GoogleIdentity:
    sub: str
    email: str
    name: str
    picture: str


class TokenVerifier:
    """Verifies Google ID tokens. Swapped for a fake in tests."""

    def __init__(self, client_id: str):
        self.client_id = client_id
        self._request = None

    def _verify_sync(self, token: str) -> dict:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token

        if self._request is None:
            self._request = g_requests.Request()  # caches Google's signing certs
        return id_token.verify_oauth2_token(token, self._request, self.client_id, clock_skew_in_seconds=10)

    async def verify(self, token: str) -> GoogleIdentity:
        try:
            info = await asyncio.to_thread(self._verify_sync, token)
        except ValueError as exc:
            raise HTTPException(401, "Google sign-in could not be verified. Please try again.") from exc
        if info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            raise HTTPException(401, "Unexpected token issuer.")
        if not info.get("email") or not info.get("email_verified"):
            raise HTTPException(401, "Your Google account email is not verified.")
        return GoogleIdentity(
            sub=str(info["sub"]),
            email=str(info["email"])[:320],
            name=str(info.get("name", ""))[:200],
            picture=str(info.get("picture", ""))[:1000],
        )


def cookie_name(s: Settings) -> str:
    # __Host- prefix: browser enforces Secure, Path=/ and no Domain (production only, needs HTTPS)
    return "__Host-br_session" if s.is_production else "br_session"


def issue_session(response: Response, user: User, s: Settings, secret: str) -> None:
    now = int(time.time())
    max_age = int(timedelta(days=s.session_days).total_seconds())
    token = jwt.encode(
        {"sub": user.id, "ver": user.session_version, "iat": now, "exp": now + max_age, "jti": secrets.token_hex(8)},
        secret,
        algorithm=ALGO,
    )
    response.set_cookie(
        cookie_name(s),
        token,
        max_age=max_age,
        httponly=True,
        secure=s.is_production,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response, s: Settings) -> None:
    response.delete_cookie(cookie_name(s), path="/", secure=s.is_production, httponly=True, samesite="lax")


async def _session_db(request: Request):
    async for session in request.app.state.db.session():
        yield session


async def optional_user(request: Request, db: AsyncSession = Depends(_session_db)) -> User | None:
    s: Settings = request.app.state.settings
    token = request.cookies.get(cookie_name(s))
    if not token:
        return None
    try:
        claims = jwt.decode(token, request.app.state.session_secret, algorithms=[ALGO], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        return None
    user = await db.get(User, claims["sub"])
    if user is None or user.session_version != claims.get("ver"):
        return None
    return user


async def require_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "Please sign in.")
    return user


get_db = _session_db
