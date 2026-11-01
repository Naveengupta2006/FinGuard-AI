"""Integration tests: database mein finguard data load hona chahiye
(load_data.py, predict.py, anomaly_detection.py, setup_readonly_user.py chala ke)."""
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src" / "analytics"))
sys.path.append(str(ROOT / "src" / "database"))

import tools                                   # noqa: E402
from connection import get_readonly_engine     # noqa: E402

CUR = dict(start="2026-10-01", end="2026-10-07")
BASE = dict(baseline_start="2026-09-17", baseline_end="2026-09-30")


def test_unknown_tool_is_rejected():
    r = tools.run_tool("drop_table", table="transactions")
    assert r["status"] == "error" and "Unknown tool" in r["error"]


def test_sql_injection_in_dimension_is_rejected():
    r = tools.run_tool("fraud_drivers", dimension="country; DROP TABLE transactions",
                       **CUR, **BASE)
    assert r["status"] == "error"


def test_bad_dates_are_rejected():
    assert tools.run_tool("fraud_kpis", start="2026-10-07", end="2026-10-01")["status"] == "error"
    assert tools.run_tool("fraud_kpis", start="yesterday", end="today")["status"] == "error"
    assert tools.run_tool("fraud_kpis", start="2020-01-01", end="2026-10-01")["status"] == "error"


def test_unexpected_parameters_are_rejected():
    r = tools.run_tool("fraud_kpis", start="2026-10-01", end="2026-10-07", sql="DELETE")
    assert r["status"] == "error"


def test_limit_is_capped():
    r = tools.run_tool("top_risky_transactions", **CUR, limit=100000)
    assert r["status"] == "ok" and r["data"]["returned"] <= tools.MAX_LIMIT


def test_kpis_match_known_numbers():
    r = tools.run_tool("fraud_kpis", **CUR)
    assert r["data"]["transactions"] == 7051
    assert r["data"]["fraud_count"] == 450


def test_input_hash_is_deterministic():
    a = tools.run_tool("fraud_kpis", **CUR)["input_hash"]
    b = tools.run_tool("fraud_kpis", **CUR)["input_hash"]
    assert a == b


def test_coverage_limitation_is_reported():
    r = tools.run_tool("top_risky_transactions", start="2026-08-10", end="2026-08-20")
    assert any("only from" in x for x in r["limitations"])


def test_readonly_user_cannot_write():
    with get_readonly_engine().connect() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text("DELETE FROM transactions"))


def test_readonly_user_cannot_read_audit_logs():
    with get_readonly_engine().connect() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text("SELECT * FROM audit_logs"))