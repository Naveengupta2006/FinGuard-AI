"""FinGuard AI REST API. Run: uvicorn main:app --app-dir src/api --reload"""
import json
import logging
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _sub in ("api", "agents", "analytics", "rag", "database", "ml"):
    sys.path.append(str(ROOT / "src" / _sub))

import joblib                                   # noqa: E402
import pandas as pd                             # noqa: E402
from fastapi import Depends, FastAPI, HTTPException, Path as ApiPath, Query, Request  # noqa: E402
from fastapi.responses import JSONResponse      # noqa: E402
from sqlalchemy import text                     # noqa: E402

import orchestrator                             # noqa: E402
import predict as predict_mod                   # noqa: E402
import retriever                                # noqa: E402
import security                                 # noqa: E402
import tools as sql_tools                       # noqa: E402
import users                                    # noqa: E402
from connection import get_engine               # noqa: E402
from schemas import (ChatRequest, InvestigationRequest, LoginRequest,  # noqa: E402
                     PolicySearchRequest, PredictRequest, ReviewRequest)
from train import add_features                  # noqa: E402

log = logging.getLogger("finguard.api")
REPORT_DIR = ROOT / "docs" / "reports"
MODEL_PATH = ROOT / "models" / "fraud_v1.joblib"
INV_ID = r"^INV-\d{3,6}$"

throttle = security.LoginThrottle()
_investigation_lock = threading.Lock()   # investigation ID race se bachne ke liye (ek time par ek run)
_engine = None


def admin_engine():
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    security._secret()                      # JWT_SECRET missing ho toh startup par hi fail
    users.ensure_users_table(admin_engine())
    yield


app = FastAPI(title="FinGuard AI API", version="1.0.0", lifespan=lifespan,
              description="Educational decision-support API. No automated actions are taken.")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def audit_event(actor: str, action: str, details: str = ""):
    try:
        with admin_engine().begin() as conn:
            conn.execute(text("INSERT INTO audit_logs (actor, action, details) VALUES (:a, :b, :d)"),
                         {"a": actor[:50], "b": action[:100], "d": details[:300]})
    except Exception:  # noqa: BLE001
        log.exception("audit write failed")


def _tool(name: str, **params) -> dict:
    out = sql_tools.run_tool(name, **params)
    if out["status"] != "ok":
        raise HTTPException(400, out.get("error", "Invalid request"))
    return out


# ---------------- public ----------------
@app.get("/api/v1/health", tags=["system"])
def health():
    checks = {}
    try:
        with sql_tools._get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:  # noqa: BLE001
        checks["database"] = False
    try:
        checks["policy_index"] = retriever._collection().count() > 0
    except Exception:  # noqa: BLE001
        checks["policy_index"] = False
    checks["model"] = MODEL_PATH.exists()
    return {"status": "ok" if all(checks.values()) else "degraded", "checks": checks}


@app.post("/api/v1/auth/login", tags=["auth"])
def login(body: LoginRequest, request: Request):
    key = f"{body.username.lower()}|{request.client.host if request.client else 'unknown'}"
    throttle.check(key)
    user = users.get_user(admin_engine(), body.username)
    ok = security.verify_password(body.password, user["password_hash"] if user else security.DUMMY_HASH)
    if not (user and user["is_active"] and ok):
        throttle.fail(key)
        audit_event(body.username, "login_failed", "invalid credentials")
        raise HTTPException(401, "Invalid credentials")
    throttle.success(key)
    audit_event(user["username"], "login_success")
    return {"access_token": security.create_token(user["username"], user["role"]),
            "token_type": "bearer", "expires_in": security.TOKEN_MINUTES * 60, "role": user["role"]}


# ---------------- viewer ----------------
@app.get("/api/v1/transactions", tags=["data"])
def list_transactions(start: str, end: str,
                      merchant_category: str | None = None, country: str | None = None,
                      customer_id: str | None = None, min_amount: float | None = Query(None, ge=0),
                      risk_band: str | None = None,
                      limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=100000),
                      user: dict = Depends(security.require_role("viewer"))):
    return _tool("search_transactions", start=start, end=end, merchant_category=merchant_category,
                 country=country, customer_id=customer_id, min_amount=min_amount,
                 risk_band=risk_band, limit=limit, offset=offset)


@app.get("/api/v1/risk/summary", tags=["risk"])
def risk_summary(start: str, end: str, user: dict = Depends(security.require_role("viewer"))):
    kpis = _tool("fraud_kpis", start=start, end=end)
    bands = {b: _tool("top_risky_transactions", start=start, end=end, band=b, limit=1)["data"]["total_in_band"]
             for b in ("HIGH", "MEDIUM", "LOW")}
    anomalies = _tool("anomaly_summary", start=start, end=end, top_n=3)
    limits = list(dict.fromkeys(kpis["limitations"] + anomalies["limitations"]))
    return {"period": {"start": start, "end": end}, "kpis": kpis["data"], "risk_bands": bands,
            "anomalies": anomalies["data"], "limitations": limits}


@app.post("/api/v1/policies/search", tags=["policy"])
def policies_search(body: PolicySearchRequest, user: dict = Depends(security.require_role("viewer"))):
    out = retriever.search_policies(body.query, k=body.k)
    if out["status"] != "ok":
        raise HTTPException(503, out.get("error", "Policy index unavailable"))
    return out


@app.get("/api/v1/investigations", tags=["investigations"])
def list_investigations(limit: int = Query(20, ge=1, le=100),
                        user: dict = Depends(security.require_role("viewer"))):
    with admin_engine().connect() as c:
        rows = c.execute(text("SELECT investigation_id, status, summary, created_at FROM investigations "
                              "ORDER BY created_at DESC LIMIT :n"), {"n": limit}).mappings().all()
    return {"investigations": [{**dict(r), "created_at": r["created_at"].isoformat()} for r in rows]}


@app.get("/api/v1/investigations/{investigation_id}", tags=["investigations"])
def get_investigation(investigation_id: str = ApiPath(pattern=INV_ID),
                      user: dict = Depends(security.require_role("viewer"))):
    path = REPORT_DIR / f"{investigation_id}.json"
    if not path.exists():
        raise HTTPException(404, "Investigation not found")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------- analyst ----------------
def _run(question: str, dr, use_llm: bool, user: dict) -> dict:
    audit_event(user["username"], "investigation_requested", question)
    with _investigation_lock:
        return orchestrator.run_investigation(question, dr.start.isoformat(), dr.end.isoformat(),
                                              use_llm=use_llm, persist=True)


@app.post("/api/v1/investigations", tags=["investigations"], status_code=201)
def start_investigation(body: InvestigationRequest, user: dict = Depends(security.require_role("analyst"))):
    return _run(body.question, body.date_range, body.use_llm, user)


@app.post("/api/v1/investigations/{investigation_id}/review", tags=["investigations"])
def review_investigation(body: ReviewRequest, investigation_id: str = ApiPath(pattern=INV_ID),
                         user: dict = Depends(security.require_role("analyst"))):
    new_status = "approved" if body.decision == "approve" else "rejected"
    with admin_engine().begin() as c:
        row = c.execute(text("SELECT status FROM investigations WHERE investigation_id = :i FOR UPDATE"),
                        {"i": investigation_id}).first()
        if row is None:
            raise HTTPException(404, "Investigation not found")
        if row[0] != "pending_human_review":
            raise HTTPException(409, f"Investigation is already '{row[0]}'")
        c.execute(text("UPDATE investigations SET status = :s WHERE investigation_id = :i"),
                  {"s": new_status, "i": investigation_id})
        c.execute(text("INSERT INTO audit_logs (actor, action, details) VALUES (:a, :b, :d)"),
                  {"a": user["username"][:50], "b": f"human_review_{new_status}:{investigation_id}",
                   "d": body.note[:300]})
    path = REPORT_DIR / f"{investigation_id}.json"
    if path.exists():
        rep = json.loads(path.read_text(encoding="utf-8"))
        rep["status"] = new_status
        rep["human_review"] = {"required": True, "status": new_status, "reviewer": user["username"],
                               "note": body.note, "reviewed_at": datetime.now(timezone.utc).isoformat()}
        path.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    return {"investigation_id": investigation_id, "status": new_status, "reviewer": user["username"]}


@app.post("/api/v1/agent/chat", tags=["agent"])
def agent_chat(body: ChatRequest, user: dict = Depends(security.require_role("analyst"))):
    """date_range diya toh investigation workflow chalta hai; nahi diya toh policy Q&A (citations ke saath)."""
    if body.date_range is not None:
        rep = _run(body.question, body.date_range, body.use_llm, user)
        return {"mode": "investigation", "reply": rep["summary"], "investigation_id": rep["investigation_id"],
                "status": rep["status"], "findings": rep["findings"], "limitations": rep["limitations"]}
    out = retriever.search_policies(body.question, k=3)
    if out["status"] != "ok":
        raise HTTPException(503, out.get("error", "Policy index unavailable"))
    if not out["results"]:
        reply = "No relevant policy passage was found. Provide a date_range to run a data investigation."
    else:
        reply = f"{out['results'][0]['text']} (Source: {out['results'][0]['citation']})"
    return {"mode": "policy", "reply": reply, "citations": [r["citation"] for r in out["results"]],
            "limitations": out["limitations"]}


@lru_cache(maxsize=1)
def _model():
    return joblib.load(MODEL_PATH)


@app.post("/api/v1/risk/predict", tags=["risk"])
def risk_predict(body: PredictRequest, user: dict = Depends(security.require_role("analyst"))):
    if not MODEL_PATH.exists():
        raise HTTPException(503, "Model not available")
    art = _model()
    df = pd.DataFrame([{
        "txn_timestamp": pd.Timestamp(body.timestamp), "amount": body.amount,
        "merchant_category": body.merchant_category, "country": body.country,
        "channel": body.channel, "device_type": body.device_type,
        "is_international": int(body.country != body.home_country)}])
    df = add_features(df)
    score = float(art["pipeline"].predict_proba(df[art["features"]])[:, 1][0])
    return {"risk_score": round(score, 4), "risk_band": predict_mod.risk_band(score),
            "model_version": art["model_version"],
            "limitations": ["risk_score is a ranking score, not a calibrated probability.",
                            "Model was trained on a synthetic dataset; educational use only.",
                            "This result must not be used to approve, deny or block anything automatically."]}