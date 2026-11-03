"""Anomaly Agent: statistical outliers aur unke reasons."""
from common import add_evidence, call_tool, instrument


@instrument("anomaly_agent")
def anomaly_agent(s):
    out = call_tool(s, "anomaly_agent", "anomaly_summary", start=s["start"], end=s["end"], top_n=5)
    if out:
        s["results"]["anomalies"] = out["data"]
        add_evidence(s, "anomalies", "anomaly_detection", out,
                     "Anomaly flags and most common reasons (Isolation Forest + customer baseline)")