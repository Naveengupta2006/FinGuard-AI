"""Audit logging: sirf orchestrator (admin connection) likhta hai. Agents ke tools read-only hain."""
import json
from pathlib import Path

from sqlalchemy import text

from common import PROJECT_ROOT
from connection import get_engine

REPORT_DIR = PROJECT_ROOT / "docs" / "reports"


def next_investigation_id(engine) -> str:
    with engine.connect() as conn:
        n = conn.execute(text(
            "SELECT COALESCE(MAX(CAST(SUBSTRING(investigation_id FROM 5) AS INTEGER)), 0) + 1 "
            "FROM investigations WHERE investigation_id ~ '^INV-[0-9]+$'")).scalar()
    return f"INV-{n:03d}"


def save_investigation(engine, report: dict, agent_runs: list, tool_calls: list) -> None:
    inv = report["investigation_id"]
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO investigations (investigation_id, question, status, summary) "
                          "VALUES (:i, :q, :s, :sum)"),
                     {"i": inv, "q": report["question"], "s": report["status"], "sum": report["summary"]})
        run_ids = {}
        for r in agent_runs:
            run_ids[r["agent"]] = conn.execute(text(
                "INSERT INTO agent_runs (investigation_id, agent_name, status, execution_time_ms) "
                "VALUES (:i, :a, :s, :t) RETURNING run_id"),
                {"i": inv, "a": r["agent"], "s": r["status"], "t": r["execution_time_ms"]}).scalar()
        for c in tool_calls:
            conn.execute(text("INSERT INTO agent_tool_calls (run_id, tool_name, input_hash, status) "
                              "VALUES (:r, :t, :h, :s)"),
                         {"r": run_ids.get(c["agent"]), "t": c["tool"], "h": c["input_hash"], "s": c["status"]})
        for action, details in [
            ("investigation_created", report["question"]),
            ("investigation_completed", f"status={report['status']}; findings={len(report['findings'])}"),
            ("human_review_pending", "Report awaits human review; no automated action taken."),
        ]:
            conn.execute(text("INSERT INTO audit_logs (actor, action, details) VALUES (:a, :b, :d)"),
                         {"a": "orchestrator", "b": f"{action}:{inv}", "d": details})


def save_report_files(report: dict, markdown: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    inv = report["investigation_id"]
    (REPORT_DIR / f"{inv}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    path = REPORT_DIR / f"{inv}.md"
    path.write_text(markdown, encoding="utf-8")
    return path