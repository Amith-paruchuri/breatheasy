"""Free / Plus plans and Razorpay billing."""

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.planner import _CAND_CACHE
from tests.test_accounts import H, FakeVerifier, sign_in

TRIP = {"origin": {"lat": 28.5672, "lng": 77.21}, "destination": {"lat": 28.6315, "lng": 77.2167}, "mode": "WALK"}
KEY, SECRET, HOOK = "rzp_test_key", "rzp_test_secret", "whsec_test"


@pytest.fixture()
def client():
    with TestClient(app, headers=H) as c:
        app.state.token_verifier = FakeVerifier()
        s = app.state.settings
        saved = s.model_dump()
        s.plans_enabled = True
        s.free_street_searches = 2
        s.plus_street_searches = 3
        s.razorpay_key_id, s.razorpay_key_secret, s.razorpay_webhook_secret = KEY, SECRET, HOOK
        s.razorpay_plan_monthly = "plan_monthly"
        yield c
        for k, v in saved.items():
            setattr(s, k, v)


def plan(c):
    _CAND_CACHE.clear()
    r = c.post("/api/routes", json=TRIP)
    assert r.status_code == 200, r.text
    return r.json()


def test_plans_off_by_default():
    with TestClient(app, headers=H) as c:
        r = c.post("/api/routes", json=TRIP).json()
        assert r["plan"] is None and not any("open data" in w for w in r["warnings"])
        assert c.get("/api/config").json()["plans"]["enabled"] is False


def test_signed_out_gets_open_data(client):
    r = plan(client)
    assert r["plan"]["plan"] == "anonymous" and r["plan"]["street_level"] is False
    assert any("Sign in" in w for w in r["warnings"])


def test_free_allowance_then_open_data(client):
    sign_in(client, "free")
    a, b, c = plan(client), plan(client), plan(client)
    assert a["plan"]["street_level"] and b["plan"]["street_level"] and b["plan"]["used"] == 2
    assert c["plan"]["street_level"] is False and any("free street-level" in w for w in c["warnings"])
    me = client.get("/api/me").json()
    assert me["plan"] == {"plan": "free", "street_level": False, "used": 2, "limit": 2, "plus_until": None}


def _subscribe(client, monkeypatch, sub_id="sub_123"):
    calls = []

    async def fake(s, method, path, body=None):
        calls.append((method, path, body))
        return {"id": sub_id}

    monkeypatch.setattr("app.routers.billing._razorpay", fake)
    r = client.post("/api/billing/subscribe", json={"period": "monthly"})
    assert r.status_code == 200, r.text
    assert r.json()["key_id"] == KEY and calls[0][2]["plan_id"] == "plan_monthly"
    return calls


def test_checkout_signature_turns_on_plus(client, monkeypatch):
    sign_in(client, "payer")
    _subscribe(client, monkeypatch)
    bad = {"razorpay_payment_id": "pay_1", "razorpay_subscription_id": "sub_123", "razorpay_signature": "0" * 64}
    assert client.post("/api/billing/verify", json=bad).status_code == 400
    sig = hmac.new(SECRET.encode(), b"pay_1|sub_123", hashlib.sha256).hexdigest()
    r = client.post("/api/billing/verify", json={**bad, "razorpay_signature": sig})
    assert r.status_code == 200 and r.json()["plan"] == "plus"
    r = plan(client)
    assert r["plan"]["plan"] == "plus" and r["plan"]["limit"] == 3 and r["plan"]["street_level"]


def test_signature_for_someone_elses_subscription_is_refused(client, monkeypatch):
    sign_in(client, "a1")
    _subscribe(client, monkeypatch, "sub_a")
    sig = hmac.new(SECRET.encode(), b"pay_9|sub_b", hashlib.sha256).hexdigest()
    r = client.post("/api/billing/verify", json={"razorpay_payment_id": "pay_9", "razorpay_subscription_id": "sub_b", "razorpay_signature": sig})
    assert r.status_code == 400


def test_webhook_renews_and_rejects_forgeries(client, monkeypatch):
    sign_in(client, "renew")
    _subscribe(client, monkeypatch, "sub_w")
    end = int(time.time()) + 30 * 86400
    body = json.dumps({"event": "subscription.charged", "payload": {"subscription": {"entity": {"id": "sub_w", "current_end": end}}}}).encode()
    # no CSRF header needed (server to server), but the signature is
    raw = TestClient(app)
    assert raw.post("/api/billing/webhook", content=body, headers={"x-razorpay-signature": "nope"}).status_code == 400
    sig = hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest()
    assert raw.post("/api/billing/webhook", content=body, headers={"x-razorpay-signature": sig}).status_code == 200
    me = client.get("/api/me").json()
    assert me["plan"]["plan"] == "plus" and me["plan"]["limit"] == 3


def test_billing_hidden_when_payments_off(client):
    app.state.settings.razorpay_key_secret = ""
    sign_in(client, "off")
    assert client.post("/api/billing/subscribe", json={"period": "monthly"}).status_code == 404
