"""Sign-in, sessions, saved places, trips, export and deletion."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import GoogleIdentity
from app.main import app

H = {"X-Requested-With": "breatheasy"}


class FakeVerifier:
    async def verify(self, token: str) -> GoogleIdentity:
        if not token.startswith("good-token-"):
            raise HTTPException(401, "Google sign-in could not be verified.")
        who = token.removeprefix("good-token-").split("-")[0]
        return GoogleIdentity(sub=f"sub-{who}", email=f"{who}@example.com", name=who.title(), picture="")


@pytest.fixture()
def client():
    with TestClient(app, headers=H) as c:
        app.state.token_verifier = FakeVerifier()
        yield c


def sign_in(c, who="amith"):
    r = c.post("/api/auth/google", json={"credential": f"good-token-{who}-padding-1234"})
    assert r.status_code == 200, r.text
    return r.json()["user"]


TRIP = {
    "departure_time": "2026-10-22T08:30:00+05:30",
    "mode": "WALK",
    "preference": "balanced",
    "origin": {"name": "AIIMS", "lat": 28.5672, "lng": 77.21},
    "destination": {"name": "Connaught Place", "lat": 28.6315, "lng": 77.2167},
    "route_source": "detour",
    "duration_s": 5600,
    "distance_m": 7600,
    "exposure_pm25": 14000,
    "fastest_exposure_pm25": 17000,
    "fastest_duration_s": 5400,
    "mean_pm25": 150,
    "data_source": "google",
}


def test_signed_out_state(client):
    c = client
    c.cookies.clear()
    r = c.get("/api/me").json()
    assert r == {"user": None, "accounts_enabled": True}
    assert c.get("/api/me/trips").status_code == 401


def test_bad_token_rejected(client):
    r = client.post("/api/auth/google", json={"credential": "forged-token-xxxxxxxxxxxxxxxx"})
    assert r.status_code == 401


def test_csrf_header_required(client):
    with TestClient(app) as bare:
        r = bare.post("/api/auth/google", json={"credential": "good-token-x-padding-1234"})
        assert r.status_code == 403


def test_full_account_lifecycle(client):
    c = client
    c.cookies.clear()
    me = sign_in(c, "amith")
    assert me["email"] == "amith@example.com"
    assert "br_session" in c.cookies
    cookie_header = c.post("/api/auth/google", json={"credential": "good-token-amith-padding-1234"}).headers["set-cookie"]
    assert "HttpOnly" in cookie_header and "SameSite=lax" in cookie_header

    # places
    p = c.post("/api/me/places", json={"label": "Home", "name": "AIIMS hostel", "lat": 28.567, "lng": 77.21})
    assert p.status_code == 201
    assert [x["label"] for x in c.get("/api/me/places").json()] == ["Home"]

    # trips + summary
    for _ in range(2):
        assert c.post("/api/me/trips", json=TRIP).status_code == 201
    trips = c.get("/api/me/trips").json()
    assert len(trips) == 2 and trips[0]["origin"]["name"] == "AIIMS"
    s = c.get("/api/me/summary").json()
    assert s["trips"] == 2 and s["exposure_avoided"] == 6000 and s["avoided_pct"] == pytest.approx(17.6, abs=0.1)
    assert s["trips_last_30_days"] == 2

    # export
    ex = c.get("/api/me/export").json()
    assert ex["account"]["email"] == "amith@example.com" and len(ex["trips"]) == 2 and len(ex["saved_places"]) == 1

    # delete one trip, then clear
    assert c.delete(f"/api/me/trips/{trips[0]['id']}").status_code == 204
    assert len(c.get("/api/me/trips").json()) == 1
    assert c.delete("/api/me/trips").status_code == 204
    assert c.get("/api/me/trips").json() == []

    # sign out
    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/me").json()["user"] is None


def test_users_cannot_touch_each_others_data(client):
    c = client
    c.cookies.clear()
    sign_in(c, "alice")
    place = c.post("/api/me/places", json={"label": "Work", "name": "X", "lat": 28.6, "lng": 77.2}).json()
    trip = c.post("/api/me/trips", json=TRIP).json()
    c.cookies.clear()
    sign_in(c, "bob")
    assert c.get("/api/me/places").json() == []
    assert c.get("/api/me/trips").json() == []
    assert c.delete(f"/api/me/places/{place['id']}").status_code == 404
    assert c.delete(f"/api/me/trips/{trip['id']}").status_code == 404


def test_sign_out_everywhere_invalidates_old_cookie(client):
    c = client
    c.cookies.clear()
    sign_in(c, "carol")
    old = dict(c.cookies)
    assert c.post("/api/auth/logout-all").status_code == 204
    c.cookies.clear()
    for k, v in old.items():
        c.cookies.set(k, v)
    assert c.get("/api/me").json()["user"] is None


def test_delete_account_removes_everything(client):
    c = client
    c.cookies.clear()
    sign_in(c, "dave")
    c.post("/api/me/places", json={"label": "Home", "name": "X", "lat": 28.6, "lng": 77.2})
    c.post("/api/me/trips", json=TRIP)
    assert c.delete("/api/me").status_code == 204
    assert c.get("/api/me").json()["user"] is None
    # signing in again creates a fresh, empty account
    sign_in(c, "dave")
    assert c.get("/api/me/places").json() == [] and c.get("/api/me/trips").json() == []


def test_validation_limits(client):
    c = client
    c.cookies.clear()
    sign_in(c, "erin")
    bad = {**TRIP, "duration_s": -5}
    assert c.post("/api/me/trips", json=bad).status_code == 422
    assert c.post("/api/me/places", json={"label": "", "name": "X", "lat": 28.6, "lng": 77.2}).status_code == 422
    assert c.post("/api/me/places", json={"label": "Home", "name": "X", "lat": 128.6, "lng": 77.2}).status_code == 422


def test_tampered_cookie_is_ignored(client):
    c = client
    c.cookies.clear()
    c.cookies.set("br_session", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.forged")
    assert c.get("/api/me").json()["user"] is None


def test_real_verifier_checks_claims(monkeypatch):
    """TokenVerifier's own checks, with Google's signature verification stubbed out."""
    import asyncio

    from google.oauth2 import id_token

    from app.auth import TokenVerifier

    claims = {}
    seen = {}

    def fake_verify(token, request, audience, clock_skew_in_seconds=0):
        seen["audience"] = audience
        if token == "bad-signature":
            raise ValueError("Could not verify token signature.")
        return dict(claims)

    monkeypatch.setattr(id_token, "verify_oauth2_token", fake_verify)
    v = TokenVerifier("my-client-id")
    v._request = object()  # skip creating a real HTTP transport

    claims.update(iss="https://accounts.google.com", sub="123", email="a@b.com", email_verified=True, name="A")
    ident = asyncio.run(v.verify("ok"))
    assert ident.sub == "123" and seen["audience"] == "my-client-id"

    for bad in ({"email_verified": False}, {"iss": "evil.example.com"}):
        claims.update(iss="https://accounts.google.com", email_verified=True)
        claims.update(bad)
        with pytest.raises(HTTPException):
            asyncio.run(v.verify("ok"))
    with pytest.raises(HTTPException):
        asyncio.run(v.verify("bad-signature"))
