"""Fraud Risk Agent: fraud drivers (dimension-wise) aur model ke HIGH-risk transactions."""
from common import add_evidence, call_tool, instrument

DIMENSIONS = ["merchant_category", "country", "channel", "device_type"]


@instrument("fraud_agent")
def fraud_agent(s):
    for dim in DIMENSIONS:
        out = call_tool(s, "fraud_agent", "fraud_drivers", dimension=dim, start=s["start"],
                        end=s["end"], baseline_start=s["baseline_start"],
                        baseline_end=s["baseline_end"], limit=5)
        if out:
            s["results"]["drivers"][dim] = out["data"]
            add_evidence(s, f"drivers:{dim}", "transaction_data", out,
                         f"Fraud rate by {dim}, period vs baseline")

    out = call_tool(s, "fraud_agent", "top_risky_transactions",
                    start=s["start"], end=s["end"], band="HIGH", limit=5)
    if out:
        s["results"]["top_risky"] = out["data"]
        add_evidence(s, "top_risky", "risk_model", out,
                     "Highest-scored transactions in the HIGH risk band (model fraud_v1)")