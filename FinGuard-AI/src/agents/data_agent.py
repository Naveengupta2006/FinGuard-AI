"""Data Intelligence Agent: data coverage aur fraud KPIs (SQL tools se)."""
from common import add_evidence, call_tool, instrument


@instrument("data_agent")
def data_agent(s):
    s["data_ok"] = False
    out = call_tool(s, "data_agent", "compare_periods", start=s["start"], end=s["end"],
                    baseline_start=s["baseline_start"], baseline_end=s["baseline_end"])
    if out is None:
        return
    d = out["data"]
    cur, base = d["current"], d["baseline"]
    s["results"]["kpis"] = d
    add_evidence(s, "kpis", "transaction_data", out,
                 f"Fraud KPIs for {cur['period']} compared with baseline {base['period']}")
    if cur["transactions"] == 0:
        s["limitations"].append("No transactions found in the requested period; no findings can be produced.")
        return
    if base["transactions"] == 0:
        s["limitations"].append("Baseline period has no transactions; comparison with baseline is unavailable.")
    s["data_ok"] = True