"""Policy Research Agent: RAG se policy passages. Policy text transaction evidence se alag source hai."""
from common import add_evidence, call_tool, instrument

QUERIES = [
    "weekly fraud rate multiple of baseline warning and critical thresholds",
    "escalation level and timing when weekly fraud rate exceeds baseline",
    "human approval required before blocking transactions or accounts",
    "evidence requirements and limitations for investigation reports",
]


@instrument("research_agent")
def research_agent(s):
    for q in QUERIES:
        out = call_tool(s, "research_agent", "policy_search", query=q, k=3)
        if out is None:
            continue
        results = out["data"]["results"]
        ev_id = add_evidence(s, f"policy:{q[:30]}", "policy_document", out,
                             f"Policy passages retrieved for: {q}")
        s["results"]["policy"].append({"query": q, "evidence_id": ev_id, "results": results})