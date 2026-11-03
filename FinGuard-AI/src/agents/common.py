"""Shared state, per-agent tool permissions, and instrumentation for all agents."""
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypedDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _sub in ("analytics", "rag", "database", "agents"):
    sys.path.append(str(PROJECT_ROOT / "src" / _sub))

import retriever            # noqa: E402
import tools as sql_tools   # noqa: E402

# Har agent sirf apne tools chala sakta hai (least privilege)
AGENT_PERMISSIONS = {
    "data_agent": {"compare_periods"},
    "fraud_agent": {"fraud_drivers", "top_risky_transactions"},
    "anomaly_agent": {"anomaly_summary"},
    "research_agent": {"policy_search"},
}

LIST_KEYS = ["evidence", "tool_calls", "agent_runs", "limitations", "errors",
             "findings", "recommendations"]


class AgentState(TypedDict, total=False):
    question: str
    start: str
    end: str
    baseline_start: str
    baseline_end: str
    investigation_id: str
    use_llm: bool
    llm: Optional[Callable[[str], str]]
    persist: bool
    data_ok: bool
    results: Dict[str, Any]
    ev_ids: Dict[str, str]
    evidence: List[dict]
    tool_calls: List[dict]
    agent_runs: List[dict]
    limitations: List[str]
    errors: List[str]
    findings: List[dict]
    recommendations: List[dict]
    report: dict


def new_state(**kw) -> AgentState:
    s: AgentState = {"results": {"drivers": {}, "policy": []}, "ev_ids": {},
                     "data_ok": False, "use_llm": False, "llm": None, "persist": True}
    for k in LIST_KEYS:
        s[k] = []
    s.update(kw)
    return s


def copy_state(state: AgentState) -> AgentState:
    s = dict(state)
    for k in LIST_KEYS:
        s[k] = list(state.get(k, []))
    s["results"] = {**state.get("results", {}),
                    "drivers": dict(state.get("results", {}).get("drivers", {})),
                    "policy": list(state.get("results", {}).get("policy", []))}
    s["ev_ids"] = dict(state.get("ev_ids", {}))
    return s


def _hash(tool: str, params: dict) -> str:
    return hashlib.sha256(json.dumps({"tool": tool, "params": params},
                                     sort_keys=True, default=str).encode()).hexdigest()[:16]


def call_tool(s: AgentState, agent: str, tool: str, **params) -> Optional[dict]:
    """Permission check -> tool call -> log. Failure par None return karta hai."""
    if tool not in AGENT_PERMISSIONS.get(agent, set()):
        raise PermissionError(f"{agent} is not allowed to use tool '{tool}'")

    t0 = time.perf_counter()
    if tool == "policy_search":
        raw = retriever.search_policies(**params)
        out = {"tool": tool, "input_hash": _hash(tool, params), "status": raw["status"],
               "data": {"results": raw.get("results", [])},
               "limitations": raw.get("limitations", []), "error": raw.get("error")}
    else:
        out = sql_tools.run_tool(tool, **params)

    s["tool_calls"].append({"agent": agent, "tool": tool, "input_hash": out["input_hash"],
                            "status": out["status"],
                            "duration_ms": int((time.perf_counter() - t0) * 1000)})
    if out["status"] != "ok":
        s["errors"].append(f"{tool}: {out.get('error')}")
        s["limitations"].append(f"Tool '{tool}' failed ({out.get('error')}); related evidence is unavailable.")
        return None
    for lim in out.get("limitations", []):
        if lim not in s["limitations"]:
            s["limitations"].append(lim)
    return out


def add_evidence(s: AgentState, key: str, source: str, out: dict, summary: str) -> str:
    ev_id = f"E{len(s['evidence']) + 1}"
    s["evidence"].append({"id": ev_id, "source": source, "tool": out["tool"],
                          "input_hash": out["input_hash"], "summary": summary,
                          "data": out["data"]})
    s["ev_ids"][key] = ev_id
    return ev_id


def instrument(agent_name: str):
    """State copy + timing + error capture. Ek agent fail ho toh poora run crash nahi hota."""
    def deco(fn):
        def wrapper(state: AgentState) -> AgentState:
            s = copy_state(state)
            t0, status = time.perf_counter(), "completed"
            try:
                fn(s)
            except Exception as exc:  # noqa: BLE001
                status = "failed"
                s["errors"].append(f"{agent_name}: {type(exc).__name__}: {exc}")
                s["limitations"].append(f"{agent_name} failed; its evidence is missing from this report.")
            s["agent_runs"].append({"agent": agent_name, "status": status,
                                    "execution_time_ms": int((time.perf_counter() - t0) * 1000)})
            return s
        wrapper.__name__ = fn.__name__
        return wrapper
    return deco