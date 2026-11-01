"""Agent tools: allowlisted, read-only, parameterized, structured output.

Agents sirf run_tool() ke through in functions ko chala sakte hain.
- Arbitrary SQL nahi: har query yahan fixed hai
- Sirf read-only DB user (finguard_readonly)
- Column names sirf allowlist se, values hamesha bind parameters se
- Har result mein status, input_hash (audit ke liye) aur limitations
"""
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT / "src" / "database"))
from connection import get_readonly_engine  # noqa: E402

MAX_RANGE_DAYS = 120
MAX_LIMIT = 50
MIN_SAMPLE = 20            # isse kam transactions wale groups "low_sample" mark hote hain
SCORED_FROM = "2026-09-24"  # risk scores / anomalies is date se available hain

DIMENSIONS = {  # allowlist: agent ka diya naam -> actual column
    "merchant_category": "merchant_category",
    "country": "country",
    "channel": "channel",
    "device_type": "device_type",
}
BANDS = {"HIGH", "MEDIUM", "LOW"}

_engine = None


class ToolError(ValueError):
    """Agent ko dikhne wala, safe error message."""


def _get_engine():
    global _engine
    if _engine is None:
        _engine = get_readonly_engine()
    return _engine


# ---------------- helpers ----------------
def _parse_range(start, end):
    try:
        s = datetime.strptime(start, "%Y-%m-%d")
        e = datetime.strptime(end, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ToolError("Dates must be strings in YYYY-MM-DD format")
    if e < s:
        raise ToolError("end date must be on or after start date")
    if (e - s).days > MAX_RANGE_DAYS:
        raise ToolError(f"Date range too large (max {MAX_RANGE_DAYS} days)")
    return s, e + timedelta(days=1)  # end exclusive


def _clean(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    return v


def _query(sql: str, params: dict) -> list:
    with _get_engine().connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [{k: _clean(v) for k, v in r.items()} for r in rows]


def _pct(num, den):
    return round(num / den * 100, 2) if den else 0.0


def _coverage_limit(start: str):
    if start < SCORED_FROM:
        return (f"Risk scores and anomaly flags exist only from {SCORED_FROM} onward "
                f"(out-of-sample period); earlier dates are not covered.")
    return None


# ---------------- tools ----------------
def fraud_kpis(start: str, end: str) -> dict:
    s, e = _parse_range(start, end)
    r = _query("""
        SELECT COUNT(*) AS transactions,
               COALESCE(SUM(is_fraud), 0) AS fraud_count,
               COALESCE(SUM(amount), 0) AS total_amount,
               COALESCE(SUM(amount) FILTER (WHERE is_fraud = 1), 0) AS fraud_amount
        FROM transactions WHERE txn_timestamp >= :s AND txn_timestamp < :e
    """, {"s": s, "e": e})[0]
    r["fraud_rate_pct"] = _pct(r["fraud_count"], r["transactions"])
    r["period"] = f"{start} to {end}"
    limits = [] if r["transactions"] else ["No transactions found in this date range."]
    return {"data": r, "limitations": limits}


def compare_periods(start: str, end: str, baseline_start: str, baseline_end: str) -> dict:
    cur = fraud_kpis(start, end)["data"]
    base = fraud_kpis(baseline_start, baseline_end)["data"]
    limits = []
    mult = None
    if base["fraud_rate_pct"] > 0:
        mult = round(cur["fraud_rate_pct"] / base["fraud_rate_pct"], 2)
    else:
        limits.append("Baseline fraud rate is 0, so a multiple cannot be computed.")
    return {"data": {"current": cur, "baseline": base,
                     "fraud_rate_change_multiple": mult}, "limitations": limits}


def fraud_drivers(dimension: str, start: str, end: str,
                  baseline_start: str, baseline_end: str, limit: int = 5) -> dict:
    if dimension not in DIMENSIONS:
        raise ToolError(f"dimension must be one of {sorted(DIMENSIONS)}")
    col = DIMENSIONS[dimension]  # allowlist se aaya, user input nahi
    limit = max(1, min(int(limit), MAX_LIMIT))

    def by_value(a, b):
        s, e = _parse_range(a, b)
        rows = _query(f"""
            SELECT {col} AS value, COUNT(*) AS transactions,
                   SUM(is_fraud) AS fraud_count
            FROM transactions WHERE txn_timestamp >= :s AND txn_timestamp < :e
            GROUP BY {col}
        """, {"s": s, "e": e})
        return {r["value"]: r for r in rows}

    cur, base = by_value(start, end), by_value(baseline_start, baseline_end)
    total_fraud = sum(r["fraud_count"] for r in cur.values())
    out = []
    for value, r in cur.items():
        b = base.get(value, {"transactions": 0, "fraud_count": 0})
        out.append({
            "value": value,
            "transactions": r["transactions"],
            "fraud_count": r["fraud_count"],
            "fraud_rate_pct": _pct(r["fraud_count"], r["transactions"]),
            "share_of_period_fraud_pct": _pct(r["fraud_count"], total_fraud),
            "baseline_transactions": b["transactions"],
            "baseline_fraud_rate_pct": _pct(b["fraud_count"], b["transactions"]),
            "low_sample": r["transactions"] < MIN_SAMPLE,
        })
    out.sort(key=lambda x: x["fraud_count"], reverse=True)
    limits = []
    if any(x["low_sample"] for x in out[:limit]):
        limits.append(f"Some groups have fewer than {MIN_SAMPLE} transactions; their rates are unreliable.")
    limits.append("Association only: these groups co-occur with fraud; this does not prove causation.")
    return {"data": {"dimension": dimension, "groups": out[:limit]}, "limitations": limits}


def top_risky_transactions(start: str, end: str, band: str = "HIGH", limit: int = 10) -> dict:
    if band not in BANDS:
        raise ToolError(f"band must be one of {sorted(BANDS)}")
    s, e = _parse_range(start, end)
    limit = max(1, min(int(limit), MAX_LIMIT))
    rows = _query("""
        SELECT t.transaction_id, t.customer_id, t.txn_timestamp AS timestamp, t.amount,
               t.merchant_category, t.country, t.channel, t.device_type,
               p.fraud_probability AS risk_score, p.risk_band, p.model_version
        FROM risk_predictions p JOIN transactions t USING (transaction_id)
        WHERE t.txn_timestamp >= :s AND t.txn_timestamp < :e AND p.risk_band = :band
        ORDER BY p.fraud_probability DESC, t.transaction_id
        LIMIT :lim
    """, {"s": s, "e": e, "band": band, "lim": limit})
    total = _query("""
        SELECT COUNT(*) AS n FROM risk_predictions p JOIN transactions t USING (transaction_id)
        WHERE t.txn_timestamp >= :s AND t.txn_timestamp < :e AND p.risk_band = :band
    """, {"s": s, "e": e, "band": band})[0]["n"]
    limits = ["risk_score is a model ranking score, not a calibrated probability."]
    cov = _coverage_limit(start)
    if cov:
        limits.append(cov)
    if not rows:
        limits.append("No scored transactions found for this band and date range.")
    return {"data": {"band": band, "total_in_band": total, "returned": len(rows),
                     "transactions": rows}, "limitations": limits}


def _normalize_reason(r: str) -> str:
    r = re.sub(r"\s*\([^)]*\)", "", r)                       # (0.6% of ...) hatao
    r = re.sub(r"amount [\d.]+x customer's typical",
               "amount far above customer's typical", r)
    return r.strip()


def anomaly_summary(start: str, end: str, top_n: int = 5) -> dict:
    s, e = _parse_range(start, end)
    top_n = max(1, min(int(top_n), MAX_LIMIT))
    rows = _query("""
        SELECT a.reason FROM anomaly_events a JOIN transactions t USING (transaction_id)
        WHERE t.txn_timestamp >= :s AND t.txn_timestamp < :e LIMIT 20000
    """, {"s": s, "e": e})
    total_txn = _query("""
        SELECT COUNT(*) AS n FROM transactions
        WHERE txn_timestamp >= :s AND txn_timestamp < :e
    """, {"s": s, "e": e})[0]["n"]
    counter = Counter()
    for r in rows:
        for part in r["reason"].split("; "):
            counter[_normalize_reason(part)] += 1
    limits = []
    cov = _coverage_limit(start)
    if cov:
        limits.append(cov)
    limits.append("Anomalies are statistical outliers vs the baseline period, not confirmed fraud.")
    return {"data": {"anomalies": len(rows), "transactions_in_range": total_txn,
                     "anomaly_rate_pct": _pct(len(rows), total_txn),
                     "top_reasons": [{"reason": k, "count": v}
                                     for k, v in counter.most_common(top_n)]},
            "limitations": limits}


# ---------------- registry (agent allowlist) ----------------
TOOLS = {
    "fraud_kpis": fraud_kpis,
    "compare_periods": compare_periods,
    "fraud_drivers": fraud_drivers,
    "top_risky_transactions": top_risky_transactions,
    "anomaly_summary": anomaly_summary,
}


def run_tool(name: str, **params) -> dict:
    """Agents ka ekmaatra entry point. Hamesha structured dict return karta hai."""
    input_hash = hashlib.sha256(
        json.dumps({"tool": name, "params": params}, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    base = {"tool": name, "input_hash": input_hash}

    if name not in TOOLS:
        return {**base, "status": "error", "error": f"Unknown tool '{name}'",
                "allowed_tools": sorted(TOOLS)}
    try:
        result = TOOLS[name](**params)
        return {**base, "status": "ok", **result}
    except ToolError as exc:
        return {**base, "status": "error", "error": str(exc)}
    except TypeError:
        return {**base, "status": "error", "error": "Invalid or missing parameters"}
    except Exception as exc:  # internal details agent ko mat dikhao
        print(f"[tools] internal error in {name}: {type(exc).__name__}: {exc}")
        return {**base, "status": "error", "error": "Internal tool error"}


if __name__ == "__main__":
    cur = ("2026-10-01", "2026-10-07")
    base = ("2026-09-17", "2026-09-30")
    calls = [
        ("compare_periods", dict(start=cur[0], end=cur[1], baseline_start=base[0], baseline_end=base[1])),
        ("fraud_drivers", dict(dimension="merchant_category", start=cur[0], end=cur[1],
                               baseline_start=base[0], baseline_end=base[1], limit=3)),
        ("top_risky_transactions", dict(start=cur[0], end=cur[1], limit=2)),
        ("anomaly_summary", dict(start=cur[0], end=cur[1], top_n=4)),
        ("drop_table", dict(table="transactions")),
    ]
    for name, params in calls:
        print(f"\n=== {name} ===")
        print(json.dumps(run_tool(name, **params), indent=2, default=str)[:1400])