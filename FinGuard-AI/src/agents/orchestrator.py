"""Risk Orchestrator: LangGraph workflow. Fixed routing: agents khud faisla nahi lete."""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from langgraph.graph import END, START, StateGraph  # noqa: E402

import audit                                     # noqa: E402
from anomaly_agent import anomaly_agent          # noqa: E402
from common import AgentState, copy_state, instrument, new_state  # noqa: E402
from connection import get_engine                # noqa: E402
from data_agent import data_agent                # noqa: E402
from fraud_agent import fraud_agent              # noqa: E402
from reporting_agent import reporting_agent      # noqa: E402
from research_agent import research_agent        # noqa: E402

BASELINE_DAYS = 14


@instrument("orchestrator")
def plan_node(s):
    s["baseline_start"] = s["baseline_end"] = ""
    try:
        st = datetime.strptime(s["start"], "%Y-%m-%d")
        en = datetime.strptime(s["end"], "%Y-%m-%d")
    except (TypeError, ValueError):
        s["limitations"].append("Invalid request: start and end must be dates in YYYY-MM-DD format.")
        return
    if en < st:
        s["limitations"].append("Invalid request: end date must be on or after the start date.")
        return
    s["baseline_end"] = (st - timedelta(days=1)).strftime("%Y-%m-%d")
    s["baseline_start"] = (st - timedelta(days=BASELINE_DAYS)).strftime("%Y-%m-%d")


def route_after_plan(s) -> str:
    return "data_agent" if s.get("baseline_start") else "reporting_agent"


def route_after_data(s) -> str:
    return "fraud_agent" if s.get("data_ok") else "reporting_agent"


def finalize_node(state: AgentState) -> AgentState:
    s = copy_state(state)
    report = s.get("report")
    if report is None:   # plan fail hua: khali, honest report
        from reporting_agent import assemble_report
        s.setdefault("start", ""); s.setdefault("end", "")
        s["baseline_start"] = s.get("baseline_start", ""); s["baseline_end"] = s.get("baseline_end", "")
        report = assemble_report(s)
        s["report"] = report
    report["tool_calls"] = len(s["tool_calls"])
    report["agent_runs"] = s["agent_runs"]
    if s.get("persist"):
        engine = get_engine()
        audit.save_investigation(engine, report, s["agent_runs"], s["tool_calls"])
        audit.save_report_files(report, render_markdown(report))
    return s


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("plan", plan_node)
    g.add_node("data_agent", data_agent)
    g.add_node("fraud_agent", fraud_agent)
    g.add_node("anomaly_agent", anomaly_agent)
    g.add_node("research_agent", research_agent)
    g.add_node("reporting_agent", reporting_agent)
    g.add_node("finalize", finalize_node)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", route_after_plan,
                            {"data_agent": "data_agent", "reporting_agent": "reporting_agent"})
    g.add_conditional_edges("data_agent", route_after_data,
                            {"fraud_agent": "fraud_agent", "reporting_agent": "reporting_agent"})
    g.add_edge("fraud_agent", "anomaly_agent")
    g.add_edge("anomaly_agent", "research_agent")
    g.add_edge("research_agent", "reporting_agent")
    g.add_edge("reporting_agent", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


def ollama_llm(prompt: str) -> str:
    from langchain_ollama import ChatOllama
    return ChatOllama(model="llama3.2:3b", temperature=0).invoke(prompt).content


def run_investigation(question: str, start: str, end: str, use_llm: bool = False,
                      persist: bool = True, llm=None) -> dict:
    inv_id = audit.next_investigation_id(get_engine()) if persist else "INV-DRYRUN"
    state = new_state(question=question, start=start, end=end, investigation_id=inv_id,
                      use_llm=use_llm, llm=llm or ollama_llm, persist=persist)
    final = build_graph().invoke(state)
    return final["report"]


def render_markdown(r: dict) -> str:
    L = [f"# Investigation {r['investigation_id']}", "",
         f"**Status:** {r['status']}  |  **Human review:** {r['human_review']['status']}",
         f"**Question:** {r['question']}",
         f"**Period:** {r['period']['start']} to {r['period']['end']} "
         f"(baseline {r['period']['baseline_start']} to {r['period']['baseline_end']})", "",
         f"## Summary ({r['summary_source']})", "", r["summary"], "", "## Findings", ""]
    L += [f"- **{f['id']}** {f['statement']} _[{', '.join(f['evidence_ids'])}]_" for f in r["findings"]] or ["- None (no verified evidence)"]
    L += ["", "## Recommendations (require human approval)", ""]
    L += [f"- {x['text']} _[{', '.join(x['evidence_ids'])}]_" for x in r["recommendations"]] or ["- None"]
    L += ["", "## Policy references", ""]
    L += [f"- {p['citation']} _[{p['evidence_id']}]_" for p in r["policy_references"]] or ["- None retrieved"]
    L += ["", "## Evidence", "", "| ID | Source | Tool | Summary |", "|---|---|---|---|"]
    L += [f"| {e['id']} | {e['source']} | {e['tool']} | {e['summary']} |" for e in r["evidence"]]
    L += ["", "## Limitations", ""] + [f"- {x}" for x in r["limitations"]]
    L += ["", f"_{r['notice']}_"]
    return "\n".join(L)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--question", default="Why has the fraud rate increased this week? Identify high-risk transactions and prepare an investigation report.")
    p.add_argument("--start", default="2026-10-01")
    p.add_argument("--end", default="2026-10-07")
    p.add_argument("--llm", action="store_true", help="Ollama se summary likhwao (optional)")
    p.add_argument("--no-persist", action="store_true")
    a = p.parse_args()
    rep = run_investigation(a.question, a.start, a.end, use_llm=a.llm, persist=not a.no_persist)
    print(render_markdown(rep))