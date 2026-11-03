"""Agent workflow tests (bina LLM ke; LLM ko stub se test karte hain).
Database mein data, scores, anomalies aur RAG index hona chahiye."""
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
for sub in ("agents", "analytics", "rag", "database"):
    sys.path.append(str(ROOT / "src" / sub))

import common                                   # noqa: E402
import orchestrator as orch                     # noqa: E402
import reporting_agent as rep                   # noqa: E402
from connection import get_engine               # noqa: E402

Q = "Why did fraud increase this week?"
CUR = ("2026-10-01", "2026-10-07")


@pytest.fixture(scope="module")
def report():
    return orch.run_investigation(Q, *CUR, persist=False)


def test_agent_cannot_use_tool_outside_its_permissions():
    s = common.new_state()
    with pytest.raises(PermissionError):
        common.call_tool(s, "data_agent", "top_risky_transactions", start=CUR[0], end=CUR[1])
    with pytest.raises(PermissionError):
        common.call_tool(s, "fraud_agent", "policy_search", query="x")
    with pytest.raises(PermissionError):
        common.call_tool(s, "unknown_agent", "fraud_kpis", start=CUR[0], end=CUR[1])


def test_workflow_produces_grounded_report(report):
    assert report["status"] == "pending_human_review"
    assert report["findings"], "findings khali nahi hone chahiye"
    ids = {e["id"] for e in report["evidence"]}
    for f in report["findings"] + report["recommendations"]:
        assert all(e in ids for e in f["evidence_ids"])
    assert any("8.74 times" in f["statement"] for f in report["findings"])


def test_report_requires_human_review(report):
    assert report["human_review"]["required"] is True
    assert report["human_review"]["reviewer"] is None
    assert any("No automated action" in r["text"] for r in report["recommendations"])


def test_policy_and_transaction_evidence_are_separate_sources(report):
    sources = {e["source"] for e in report["evidence"]}
    assert "transaction_data" in sources and "policy_document" in sources


def test_no_data_period_gives_empty_findings():
    r = orch.run_investigation(Q, "2026-01-01", "2026-01-07", persist=False)
    assert r["findings"] == [] and r["status"] == "no_evidence"
    assert any("No transactions" in x for x in r["limitations"])


def test_invalid_dates_give_empty_findings():
    r = orch.run_investigation(Q, "yesterday", "today", persist=False)
    assert r["findings"] == [] and any("Invalid request" in x for x in r["limitations"])


def test_llm_summary_with_invented_number_is_rejected():
    r = orch.run_investigation(Q, *CUR, use_llm=True, persist=False,
                               llm=lambda p: "Fraud rose by 99% and 12345 accounts were affected.")
    assert r["summary_source"] == "template"
    assert any("rejected" in x for x in r["limitations"])


def test_llm_summary_with_grounded_numbers_is_accepted(report):
    first = report["findings"][0]["statement"]
    r = orch.run_investigation(Q, *CUR, use_llm=True, persist=False, llm=lambda p: first)
    assert r["summary_source"] == "llm"


def test_llm_failure_falls_back_to_template():
    def broken(prompt):
        raise ConnectionError("ollama not running")
    r = orch.run_investigation(Q, *CUR, use_llm=True, persist=False, llm=broken)
    assert r["summary_source"] == "template" and r["findings"]
    assert any("unavailable" in x for x in r["limitations"])


def test_finding_without_evidence_is_removed():
    report = {"evidence": [{"id": "E1"}],
              "findings": [{"id": "F1", "statement": "ok", "evidence_ids": ["E1"]},
                           {"id": "F2", "statement": "made up", "evidence_ids": []},
                           {"id": "F3", "statement": "bad ref", "evidence_ids": ["E9"]}]}
    assert len(rep.validate_report(report)) == 2


def test_summary_verifier():
    f = [{"statement": "Fraud rate was 6.38% versus 0.73%, 8.74 times higher."}]
    assert rep.verify_summary("Fraud was 6.38% versus 0.73% (8.74 times).", f) is None
    assert rep.verify_summary("Fraud was 7% higher.", f) is not None


def test_audit_rows_are_written_and_cleaned_up():
    r = orch.run_investigation(Q, *CUR, persist=True)
    inv = r["investigation_id"]
    engine = get_engine()
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT COUNT(*) FROM investigations WHERE investigation_id=:i"), {"i": inv}).scalar() == 1
            runs = c.execute(text("SELECT COUNT(*) FROM agent_runs WHERE investigation_id=:i"), {"i": inv}).scalar()
            calls = c.execute(text("SELECT COUNT(*) FROM agent_tool_calls WHERE run_id IN "
                                   "(SELECT run_id FROM agent_runs WHERE investigation_id=:i)"), {"i": inv}).scalar()
            assert runs >= 6 and calls >= 9
    finally:  # test ka data hata do
        with engine.begin() as c:
            c.execute(text("DELETE FROM agent_tool_calls WHERE run_id IN "
                           "(SELECT run_id FROM agent_runs WHERE investigation_id=:i)"), {"i": inv})
            c.execute(text("DELETE FROM agent_runs WHERE investigation_id=:i"), {"i": inv})
            c.execute(text("DELETE FROM investigations WHERE investigation_id=:i"), {"i": inv})
            c.execute(text("DELETE FROM audit_logs WHERE action LIKE :a"), {"a": f"%:{inv}"})
        for ext in ("json", "md"):
            (ROOT / "docs" / "reports" / f"{inv}.{ext}").unlink(missing_ok=True)