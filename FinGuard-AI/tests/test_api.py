"""API tests. Database + RAG index + model ready hona chahiye. .env mein JWT_SECRET (32+ chars)."""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
for sub in ("api", "agents", "analytics", "rag", "database", "ml"):
    sys.path.append(str(ROOT / "src" / sub))

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)   # .env mein na ho toh bhi tests chalein

import main                                    # noqa: E402
import security                                # noqa: E402
import users                                   # noqa: E402
from connection import get_engine              # noqa: E402

PW = "correct-horse-battery"
TEST_USERS = {"test_viewer": "viewer", "test_analyst": "analyst"}
RANGE = {"start": "2026-10-01", "end": "2026-10-07"}


@pytest.fixture(scope="module")
def client():
    eng = get_engine()
    users.ensure_users_table(eng)
    for name, role in TEST_USERS.items():
        users.upsert_user(eng, name, PW, role)
    with TestClient(main.app) as c:
        yield c
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM app_users WHERE username LIKE 'test\\_%'"))
        conn.execute(text("DELETE FROM audit_logs WHERE actor LIKE 'test\\_%'"))


def token(client, user):
    r = client.post("/api/v1/auth/login", json={"username": user, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------- authentication ----------------
def test_health_is_public(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and "checks" in r.json()


def test_protected_endpoint_requires_token(client):
    assert client.get("/api/v1/risk/summary", params=RANGE).status_code == 401


def test_wrong_password_is_rejected(client):
    r = client.post("/api/v1/auth/login", json={"username": "test_viewer", "password": "wrong-password-1"})
    assert r.status_code == 401


def test_unknown_user_gets_same_error_as_wrong_password(client):
    a = client.post("/api/v1/auth/login", json={"username": "test_nobody", "password": "wrong-password-1"})
    b = client.post("/api/v1/auth/login", json={"username": "test_viewer", "password": "wrong-password-1"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_login_throttling(client):
    main.throttle = security.LoginThrottle()
    codes = [client.post("/api/v1/auth/login", json={"username": "test_throttle", "password": "wrong-password-1"}).status_code
             for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    main.throttle = security.LoginThrottle()


def test_expired_token_is_rejected(client):
    now = datetime.now(timezone.utc)
    t = jwt.encode({"sub": "test_viewer", "role": "viewer", "iss": security.ISSUER,
                    "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)},
                   security._secret(), algorithm="HS256")
    assert client.get("/api/v1/risk/summary", params=RANGE, headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_token_signed_with_wrong_secret_is_rejected(client):
    now = datetime.now(timezone.utc)
    t = jwt.encode({"sub": "attacker", "role": "admin", "iss": security.ISSUER,
                    "iat": now, "exp": now + timedelta(hours=1)}, "a-different-secret-" + "y" * 30, algorithm="HS256")
    assert client.get("/api/v1/risk/summary", params=RANGE, headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_unsigned_alg_none_token_is_rejected(client):
    now = datetime.now(timezone.utc)
    t = jwt.encode({"sub": "attacker", "role": "admin", "iss": security.ISSUER,
                    "iat": now, "exp": now + timedelta(hours=1)}, key=None, algorithm="none")
    assert client.get("/api/v1/risk/summary", params=RANGE, headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_password_hashing():
    h = security.hash_password("some-long-password")
    assert security.verify_password("some-long-password", h)
    assert not security.verify_password("other-password-1", h)
    assert "some-long-password" not in h


# ---------------- authorization (roles) ----------------
def test_viewer_can_read_but_not_start_investigation(client):
    h = token(client, "test_viewer")
    assert client.get("/api/v1/risk/summary", params=RANGE, headers=h).status_code == 200
    r = client.post("/api/v1/investigations", headers=h, json={"question": "Why did fraud increase?", "date_range": RANGE})
    assert r.status_code == 403


def test_viewer_cannot_predict_or_chat_or_review(client):
    h = token(client, "test_viewer")
    assert client.post("/api/v1/agent/chat", headers=h, json={"question": "what is escalation"}).status_code == 403
    assert client.post("/api/v1/investigations/INV-001/review", headers=h, json={"decision": "approve"}).status_code == 403


# ---------------- data endpoints ----------------
def test_risk_summary_numbers(client):
    r = client.get("/api/v1/risk/summary", params=RANGE, headers=token(client, "test_viewer")).json()
    assert r["kpis"]["transactions"] == 7051 and r["kpis"]["fraud_count"] == 450
    assert set(r["risk_bands"]) == {"HIGH", "MEDIUM", "LOW"}


def test_transactions_search_and_limit_cap(client):
    h = token(client, "test_viewer")
    r = client.get("/api/v1/transactions", headers=h, params={**RANGE, "country": "NG", "risk_band": "HIGH", "limit": 5})
    assert r.status_code == 200 and r.json()["data"]["returned"] <= 5
    assert client.get("/api/v1/transactions", headers=h, params={**RANGE, "limit": 100000}).status_code == 422


def test_sql_injection_in_filter_is_rejected(client):
    h = token(client, "test_viewer")
    r = client.get("/api/v1/transactions", headers=h, params={**RANGE, "country": "NG' OR 1=1--"})
    assert r.status_code == 400


def test_invalid_dates_are_rejected(client):
    h = token(client, "test_viewer")
    assert client.get("/api/v1/risk/summary", headers=h, params={"start": "2026-10-07", "end": "2026-10-01"}).status_code == 400
    assert client.get("/api/v1/risk/summary", headers=h, params={"start": "x", "end": "y"}).status_code == 400


def test_policy_search_returns_citations(client):
    r = client.post("/api/v1/policies/search", headers=token(client, "test_viewer"),
                    json={"query": "weekly fraud rate above 5 times baseline escalation", "k": 3}).json()
    assert r["status"] == "ok" and all("citation" in x for x in r["results"])


def test_predict_returns_score_with_limitations(client):
    body = {"amount": 9000, "timestamp": "2026-10-03T02:00:00", "merchant_category": "gift_cards",
            "country": "NG", "home_country": "IN", "channel": "online", "device_type": "new"}
    r = client.post("/api/v1/risk/predict", headers=token(client, "test_analyst"), json=body).json()
    assert 0 <= r["risk_score"] <= 1 and r["risk_band"] in {"HIGH", "MEDIUM", "LOW"} and r["limitations"]


def test_predict_rejects_bad_input(client):
    body = {"amount": -5, "timestamp": "2026-10-03T02:00:00", "merchant_category": "gift_cards; DROP",
            "country": "NG", "home_country": "IN", "channel": "online", "device_type": "new"}
    assert client.post("/api/v1/risk/predict", headers=token(client, "test_analyst"), json=body).status_code == 422


def test_chat_without_dates_is_policy_qa(client):
    r = client.post("/api/v1/agent/chat", headers=token(client, "test_analyst"),
                    json={"question": "who approves blocking a customer account?"}).json()
    assert r["mode"] == "policy" and "reply" in r


# ---------------- investigation + human review + audit ----------------
def _cleanup(inv):
    with get_engine().begin() as c:
        c.execute(text("DELETE FROM agent_tool_calls WHERE run_id IN (SELECT run_id FROM agent_runs WHERE investigation_id=:i)"), {"i": inv})
        c.execute(text("DELETE FROM agent_runs WHERE investigation_id=:i"), {"i": inv})
        c.execute(text("DELETE FROM investigations WHERE investigation_id=:i"), {"i": inv})
        c.execute(text("DELETE FROM audit_logs WHERE action LIKE :a"), {"a": f"%:{inv}"})
    for ext in ("json", "md"):
        (ROOT / "docs" / "reports" / f"{inv}.{ext}").unlink(missing_ok=True)


def test_investigation_review_flow(client):
    h = token(client, "test_analyst")
    r = client.post("/api/v1/investigations", headers=h,
                    json={"question": "Why did fraud increase this week?", "date_range": RANGE})
    assert r.status_code == 201
    inv = r.json()["investigation_id"]
    try:
        assert r.json()["status"] == "pending_human_review" and r.json()["findings"]
        assert client.get(f"/api/v1/investigations/{inv}", headers=h).status_code == 200

        rv = client.post(f"/api/v1/investigations/{inv}/review", headers=h,
                         json={"decision": "approve", "note": "checked evidence"})
        assert rv.status_code == 200 and rv.json()["reviewer"] == "test_analyst"
        again = client.post(f"/api/v1/investigations/{inv}/review", headers=h, json={"decision": "reject"})
        assert again.status_code == 409          # decision dobara nahi badal sakte

        rep = client.get(f"/api/v1/investigations/{inv}", headers=h).json()
        assert rep["human_review"]["status"] == "approved" and rep["human_review"]["reviewer"] == "test_analyst"
        with get_engine().connect() as c:
            n = c.execute(text("SELECT COUNT(*) FROM audit_logs WHERE action = :a AND actor = 'test_analyst'"),
                          {"a": f"human_review_approved:{inv}"}).scalar()
        assert n == 1
    finally:
        _cleanup(inv)


def test_investigation_id_path_is_validated(client):
    h = token(client, "test_viewer")
    assert client.get("/api/v1/investigations/..%2F..%2F.env", headers=h).status_code in (404, 422)
    assert client.get("/api/v1/investigations/INV-ABC", headers=h).status_code == 422
    assert client.get("/api/v1/investigations/INV-999999", headers=h).status_code == 404