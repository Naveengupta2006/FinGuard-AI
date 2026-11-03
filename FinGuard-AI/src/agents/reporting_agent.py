"""Investigation & Reporting Agent.

Findings sirf tool evidence se, templates ke zariye banti hain (LLM se nahi).
LLM (optional) sirf summary ki language likhta hai, aur uske har number ko verify kiya jaata hai.
"""
import re
from typing import Callable, List, Optional

from common import instrument

NUM_RE = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?")
EXCEEDS_RE = re.compile(r"exceeds (\d+(?:\.\d+)?) times", re.I)
BETWEEN_RE = re.compile(r"between (\d+(?:\.\d+)?) and (\d+(?:\.\d+)?) times", re.I)
THRESHOLD_RE = re.compile(r"above (\d+(?:\.\d+)?) times (?:the )?(?:trailing[^,.]*?)?baseline", re.I)


# ---------------- findings (deterministic) ----------------
def _drivers_finding(dim: str, data: dict) -> Optional[str]:
    hits = []
    for g in data["groups"]:
        elevated = g["fraud_rate_pct"] >= 5 and g["fraud_rate_pct"] >= 3 * g["baseline_fraud_rate_pct"]
        if elevated and not g["low_sample"]:
            hits.append(f"'{g['value']}' {g['fraud_rate_pct']}% ({g['fraud_count']} of {g['transactions']} "
                        f"transactions; baseline {g['baseline_fraud_rate_pct']}%)")
    if not hits:
        return None
    return (f"Elevated fraud is concentrated in {dim}: " + "; ".join(hits) +
            ". This is an association, not proof of cause.")


def _policy_thresholds(s) -> List[tuple]:
    """Retrieved policy text se 'above N times baseline' thresholds nikalo."""
    found, seen = [], set()
    for block in s["results"]["policy"]:
        for r in block["results"]:
            for m in THRESHOLD_RE.finditer(r["text"]):
                key = (float(m.group(1)), r["citation"])
                if key not in seen:
                    seen.add(key)
                    found.append((key[0], r["citation"], block["evidence_id"], r["text"]))
    return found


def build_findings(s) -> List[dict]:
    res, ev, findings = s["results"], s["ev_ids"], []
    if not s.get("data_ok"):      # data nahi = koi finding nahi (evidence ke bina kuch nahi likhna)
        return findings

    def add(statement, evidence_ids):
        findings.append({"id": f"F{len(findings) + 1}", "statement": statement,
                         "evidence_ids": [e for e in evidence_ids if e]})

    k = res.get("kpis")
    mult = None
    if k:
        cur, base, mult = k["current"], k["baseline"], k["fraud_rate_change_multiple"]
        text = (f"Fraud rate was {cur['fraud_rate_pct']}% ({cur['fraud_count']} of {cur['transactions']} "
                f"transactions) in {cur['period']}, versus {base['fraud_rate_pct']}% "
                f"({base['fraud_count']} of {base['transactions']}) in the baseline {base['period']}")
        if base["transactions"] == 0:
            text = (f"Fraud rate was {cur['fraud_rate_pct']}% ({cur['fraud_count']} of {cur['transactions']} "
                    f"transactions) in {cur['period']}; no baseline data is available for comparison.")
        elif mult is not None and mult >= 1.5:
            text += f", which is {mult} times the baseline rate."
        else:
            text += "; there is no material increase over the baseline."
        add(text, [ev.get("kpis")])

    for dim, data in res["drivers"].items():
        stmt = _drivers_finding(dim, data)
        if stmt:
            add(stmt, [ev.get(f"drivers:{dim}")])

    tr = res.get("top_risky")
    if tr and tr["total_in_band"] > 0:
        ids = ", ".join(t["transaction_id"] for t in tr["transactions"])
        add(f"{tr['total_in_band']} transactions were scored in the HIGH risk band during the period; "
            f"the highest-scored are {ids}. The risk score is a ranking score, not a probability.",
            [ev.get("top_risky")])

    an = res.get("anomalies")
    if an and an["anomalies"] > 0:
        reasons = "; ".join(f"{r['reason']} ({r['count']})" for r in an["top_reasons"])
        add(f"{an['anomalies']} of {an['transactions_in_range']} transactions ({an['anomaly_rate_pct']}%) "
            f"were flagged as statistical anomalies. Most common reasons: {reasons}. "
            f"Anomalies are outliers, not confirmed fraud.", [ev.get("anomalies")])

    if mult is not None:
        exceeded = [t for t in _policy_thresholds(s) if mult >= t[0]]
        if exceeded:
            thr, cite, pev, _ = max(exceeded, key=lambda t: t[0])
            add(f"The fraud-rate multiple ({mult}x) exceeds the {thr:g}x threshold stated in {cite}.",
                [ev.get("kpis"), pev])
    elif res.get("policy"):
        s["limitations"].append("Fraud-rate multiple could not be computed, so policy thresholds were not compared.")
    return findings


def _matching_escalation(policy_hits, mult):
    """ESC-003 ka wo section jiski range mein observed multiple aata hai (retrieved text se parse)."""
    best = None
    for r, eid in policy_hits:
        if r["doc_id"] != "ESC-003":
            continue
        lo = None
        m = BETWEEN_RE.search(r["text"])
        if m and float(m.group(1)) <= mult < float(m.group(2)):
            lo = float(m.group(1))
        m = EXCEEDS_RE.search(r["text"])
        if m and mult > float(m.group(1)):
            lo = float(m.group(1))
        if lo is not None and (best is None or lo > best[0]):
            best = (lo, r, eid)
    return (best[1], best[2]) if best else None


def build_recommendations(s, findings) -> List[dict]:
    recs = []
    policy_hits = [(r, b["evidence_id"]) for b in s["results"]["policy"] for r in b["results"]]

    def find(doc, sec):
        for r, eid in policy_hits:
            if r["doc_id"] == doc and r["section"].startswith(sec):
                return r, eid
        return None

    mult = (s["results"].get("kpis") or {}).get("fraud_rate_change_multiple")
    if any("exceeds the" in f["statement"] for f in findings) and mult is not None:
        esc = _matching_escalation(policy_hits, mult)
        if esc:
            recs.append({"text": f"Escalate for human review as described in {esc[0]['citation']}.",
                         "evidence_ids": [esc[1], s["ev_ids"].get("kpis")]})
        else:
            s["limitations"].append("No escalation section matching the observed fraud-rate multiple was "
                                    "retrieved; check the Risk Escalation Guidelines manually.")
    if s["ev_ids"].get("top_risky") and s["results"].get("top_risky", {}).get("returned"):
        n = s["results"]["top_risky"]["returned"]
        recs.append({"text": f"Analyst to review the {n} highest-scored transactions listed in evidence "
                             f"{s['ev_ids']['top_risky']}.", "evidence_ids": [s["ev_ids"]["top_risky"]]})
    appr = find("ESC-003", "3")
    cite = f" ({appr[0]['citation']})" if appr else ""
    recs.append({"text": "No automated action is taken by this system. Blocking transactions, restricting "
                         f"accounts or contacting customers requires documented human approval{cite}.",
                 "evidence_ids": [appr[1]] if appr else []})
    return recs


# ---------------- LLM summary + guardrail ----------------
def _numbers(text: str) -> set:
    return {float(x) for x in NUM_RE.findall(text)}


def template_summary(s, findings) -> str:
    if not findings:
        return "No verified evidence was found for this request. See limitations."
    return " ".join(f["statement"] for f in findings[:2])


def llm_summary(findings: List[dict], llm: Callable[[str], str]) -> str:
    lines = "\n".join(f"{f['id']}: {f['statement']}" for f in findings)
    prompt = ("You assist a fraud analyst. Write a summary of 3-4 sentences using ONLY the verified "
              "findings below. Do not add facts, names or numbers that are not in the findings, copy "
              "numbers exactly, do not recommend blocking transactions or accounts, and do not mention "
              "these rules.\n\nFindings:\n" + lines + "\n\nSummary:")
    return llm(prompt).strip()


def verify_summary(text: str, findings: List[dict]) -> Optional[str]:
    """None = ok, warna rejection ki wajah."""
    if not text:
        return "empty output"
    if len(text) > 1500:
        return "too long"
    allowed = set()
    for f in findings:
        allowed |= _numbers(f["statement"])
    extra = sorted(n for n in _numbers(text) if n not in allowed)
    if extra:
        return f"contains numbers not present in the findings: {extra[:5]}"
    return None


# ---------------- validation ----------------
def validate_report(report: dict) -> List[str]:
    ids = {e["id"] for e in report["evidence"]}
    problems = []
    for f in report["findings"]:
        if not f["evidence_ids"] or any(e not in ids for e in f["evidence_ids"]):
            problems.append(f"{f['id']}: missing or unknown evidence")
    return problems


def assemble_report(s) -> dict:
    findings = build_findings(s)
    recs = build_recommendations(s, findings) if findings else []
    report = {
        "status": "pending_human_review" if findings else "no_evidence",
        "investigation_id": s.get("investigation_id"),
        "question": s["question"],
        "period": {"start": s["start"], "end": s["end"],
                   "baseline_start": s["baseline_start"], "baseline_end": s["baseline_end"]},
        "findings": findings, "recommendations": recs,
        "evidence": s["evidence"], "limitations": [],
        "policy_references": [], "summary": "", "summary_source": "template",
        "human_review": {"required": True, "status": "pending", "reviewer": None},
        "notice": "Educational decision-support output. No automated actions are taken.",
    }

    bad = validate_report(report)
    if bad:
        keep = {f["id"] for f in findings} - {b.split(":")[0] for b in bad}
        report["findings"] = [f for f in findings if f["id"] in keep]
        s["limitations"].append(f"{len(bad)} finding(s) were removed because they lacked valid evidence.")
        if not report["findings"]:
            report["status"], report["recommendations"] = "no_evidence", []

    summary, source = template_summary(s, report["findings"]), "template"
    if s.get("use_llm") and report["findings"]:
        try:
            candidate = llm_summary(report["findings"], s["llm"])
            problem = verify_summary(candidate, report["findings"])
            if problem is None:
                summary, source = candidate, "llm"
            else:
                s["limitations"].append(f"LLM summary was rejected ({problem}); a template summary is shown.")
        except Exception as exc:  # noqa: BLE001
            s["limitations"].append(f"LLM summary unavailable ({type(exc).__name__}); a template summary is shown.")
    report["summary"], report["summary_source"] = summary, source

    seen = set()
    for block in s["results"]["policy"]:
        for r in block["results"]:
            if r["citation"] not in seen and len(seen) < 6:
                seen.add(r["citation"])
                report["policy_references"].append({"citation": r["citation"], "score": r["score"],
                                                    "excerpt": r["text"][:220], "evidence_id": block["evidence_id"]})
    if not report["policy_references"]:
        s["limitations"].append("No policy passages were retrieved; policy references are unavailable.")

    uniq = []
    for lim in s["limitations"]:
        if lim not in uniq:
            uniq.append(lim)
    report["limitations"] = uniq
    return report


@instrument("reporting_agent")
def reporting_agent(s):
    s["findings"] = []
    s["report"] = assemble_report(s)
    s["findings"] = s["report"]["findings"]
    s["recommendations"] = s["report"]["recommendations"]