import { api } from "../api.js";
import { badge, card, clear, fmtDateTime, h, loading, pageHeader, showError, statusBadge, table, toast, truncate } from "../ui.js";

const DEFAULT_Q = "Why has the fraud rate increased? Identify high-risk transactions and prepare an investigation report.";

export async function render(root, ctx, param) {
    return param ? detail(root, ctx, param) : list(root, ctx);
}

// ---------------- list + new investigation ----------------
async function list(root, ctx) {
    loading(root);
    let res;
    try { res = await api("GET", "/investigations", { params: { limit: 50 } }); } catch (e) { return showError(root, e); }

    const parts = [pageHeader("Investigations", "Agent-generated reports awaiting or after human review")];
    if (ctx.canWrite) {
        const q = h("textarea", { id: "question", rows: 3, maxlength: 500, "aria-label": "Question" }, DEFAULT_Q);
        const llm = h("input", { type: "checkbox", id: "use-llm" });
        const btn = h("button", { type: "submit", class: "btn btn-primary" }, "Run investigation");
        const note = h("p", { class: "muted small" }, `Period: ${ctx.range.start} to ${ctx.range.end}`);
        const form = h("form", { class: "stack" }, q,
            h("label", { class: "check" }, llm, " Let the local LLM write the summary (slower, optional)"), note, btn);
        form.addEventListener("submit", async (ev) => {
            ev.preventDefault();
            btn.disabled = true; btn.textContent = "Agents are working…";
            try {
                const rep = await api("POST", "/investigations", {
                    timeout: 300000, body: {
                        question: q.value, use_llm: llm.checked, date_range: ctx.range
                    }
                });
                toast(`Created ${rep.investigation_id}`, "good");
                location.hash = `#/investigations/${rep.investigation_id}`;
            } catch (e) { toast(e.message, "bad"); btn.disabled = false; btn.textContent = "Run investigation"; }
        });
        parts.push(card("Start a new investigation", form));
    }
    parts.push(card("Recent investigations", table([
        { key: "investigation_id", label: "ID" },
        { key: "status", label: "Status", fmt: (v) => statusBadge(v) },
        { key: "summary", label: "Summary", fmt: (v) => truncate(v, 140) },
        { key: "created_at", label: "Created", fmt: fmtDateTime },
    ], res.investigations, { onRowClick: (r) => { location.hash = `#/investigations/${r.investigation_id}`; }, empty: "No investigations yet." })));
    clear(root).append(...parts);
}

// ---------------- detail ----------------
async function detail(root, ctx, id) {
    loading(root);
    let rep;
    try { rep = await api("GET", `/investigations/${encodeURIComponent(id)}`); } catch (e) { return showError(root, e); }

    const hr = rep.human_review;
    const parts = [
        h("a", { href: "#/investigations", class: "back" }, "← All investigations"),
        pageHeader(rep.investigation_id, rep.question, statusBadge(rep.status)),
        card(`Summary (${rep.summary_source})`, h("p", {}, rep.summary)),
        card("Findings", rep.findings.length
            ? h("ol", { class: "findings" }, rep.findings.map((f) => h("li", {},
                h("span", {}, f.statement), " ", ...f.evidence_ids.map((e) => badge(e, "neutral")))))
            : h("p", { class: "muted" }, "No verified evidence was found, so there are no findings.")),
    ];
    if (rep.recommendations.length) {
        parts.push(card("Recommendations (require human approval)", h("ul", {}, rep.recommendations.map((r) => h("li", {}, r.text, " ",
            ...r.evidence_ids.map((e) => badge(e, "neutral")))))));
    }
    if (rep.policy_references.length) {
        parts.push(card("Policy references", h("ul", {}, rep.policy_references.map((p) =>
            h("li", {}, h("strong", {}, p.citation), h("div", { class: "muted small" }, p.excerpt))))));
    }
    parts.push(
        h("details", { class: "card" }, h("summary", {}, `Evidence (${rep.evidence.length})`),
            table([{ key: "id", label: "ID" }, { key: "source", label: "Source" }, { key: "tool", label: "Tool" }, { key: "summary", label: "Summary" }], rep.evidence)),
        h("details", { class: "card", open: true }, h("summary", {}, "Limitations"),
            h("ul", {}, rep.limitations.map((l) => h("li", {}, l)))));

    // ---- human review ----
    if (rep.status === "pending_human_review" && ctx.canWrite) {
        const decision = h("select", { id: "decision", "aria-label": "Decision" },
            h("option", { value: "approve" }, "Approve"), h("option", { value: "reject" }, "Reject"));
        const note = h("input", { type: "text", id: "note", maxlength: 500, placeholder: "Note (optional)" });
        const btn = h("button", { type: "submit", class: "btn btn-primary" }, "Submit review");
        const form = h("form", { class: "toolbar wrap" }, decision, note, btn);
        form.addEventListener("submit", async (ev) => {
            ev.preventDefault();
            btn.disabled = true;
            try {
                await api("POST", `/investigations/${encodeURIComponent(id)}/review`, { body: { decision: decision.value, note: note.value } });
                toast("Review saved", "good");
                await detail(root, ctx, id);
            } catch (e) { toast(e.message, "bad"); btn.disabled = false; }
        });
        parts.push(card("Human review", h("p", { class: "muted" }, "No action is taken automatically. Your decision is recorded in the audit log."), form));
    } else if (rep.status === "pending_human_review") {
        parts.push(card("Human review", h("p", { class: "muted" }, "Waiting for an analyst to review this investigation.")));
    } else if (hr && hr.reviewer) {
        parts.push(card("Human review", h("p", {}, `${hr.status} by `, h("strong", {}, hr.reviewer), hr.note ? ` — “${hr.note}”` : "")));
    }
    parts.push(h("p", { class: "muted small" }, rep.notice));
    clear(root).append(...parts);
}