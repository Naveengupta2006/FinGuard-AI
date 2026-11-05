import { api } from "../api.js";
import { addDays, previousPeriod } from "../dates.js";
import { barChart, lineChart } from "../charts.js";
import { card, clear, fmtInt, fmtMoney, h, kpi, loading, pageHeader, showError, table, toast } from "../ui.js";

const DIMENSIONS = { merchant_category: "Merchant category", country: "Country", channel: "Channel", device_type: "Device type" };

export async function render(root, ctx) {
    const { start, end } = ctx.range;
    loading(root);
    let cur, base;
    try {
        const prev = previousPeriod(start, end);
        [cur, base] = await Promise.all([
            api("GET", "/risk/summary", { params: { start, end } }),
            api("GET", "/risk/summary", { params: prev }).catch(() => null),
        ]);
    } catch (e) { return showError(root, e); }

    const k = cur.kpis;
    let delta = null, deltaTone = "";
    if (base && base.kpis.transactions > 0) {
        const d = k.fraud_rate_pct - base.kpis.fraud_rate_pct;
        delta = `${d >= 0 ? "▲" : "▼"} ${Math.abs(d).toFixed(2)} pp vs previous period`;
        deltaTone = d > 0 ? "bad" : "good";
    }
    const bands = cur.risk_bands;
    const a = cur.anomalies;

    const trendBox = h("div", {}, h("p", { class: "muted" }, "Loading trend…"));
    const driverBox = h("div", {});
    const select = h("select", { id: "dimension", "aria-label": "Break down by" },
        Object.entries(DIMENSIONS).map(([v, l]) => h("option", { value: v }, l)));

    clear(root).append(
        pageHeader("Overview", `${start} to ${end}`),
        h("div", { class: "grid grid-4" },
            kpi("Transactions", fmtInt(k.transactions)),
            kpi("Fraud cases", fmtInt(k.fraud_count)),
            kpi("Fraud rate", `${k.fraud_rate_pct}%`, { sub: delta, tone: deltaTone }),
            kpi("Fraud amount", fmtMoney(k.fraud_amount))),
        h("div", { class: "grid grid-3" },
            kpi("HIGH risk", fmtInt(bands.HIGH), { tone: "bad" }),
            kpi("MEDIUM risk", fmtInt(bands.MEDIUM), { tone: "warn" }),
            kpi("LOW risk", fmtInt(bands.LOW), { tone: "good" })),
        start < ctx.coverage.scored_from
            ? h("p", { class: "muted small" }, `Risk bands exist only for transactions from ${ctx.coverage.scored_from} onward.`) : null,
        card("Daily fraud rate", trendBox),
        card("What is driving fraud?", h("div", { class: "toolbar" }, h("label", {}, "Break down by ", select)), driverBox),
        card("Anomalies",
            h("div", { class: "grid grid-2" },
                kpi("Flagged transactions", fmtInt(a.anomalies), { sub: `${a.anomaly_rate_pct}% of transactions` }),
                a.top_reasons.length
                    ? table([{ key: "reason", label: "Most common reason" }, { key: "count", label: "Count", class: "num", fmt: fmtInt }], a.top_reasons)
                    : h("p", { class: "muted" }, "No anomalies in this period."))),
        h("details", { class: "card" }, h("summary", {}, "Limitations"),
            h("ul", {}, cur.limitations.map((l) => h("li", {}, l)))));

    async function loadTrend() {
        const last = ctx.coverage.last_date;
        const first = ctx.coverage.first_date > addDays(last, -119) ? ctx.coverage.first_date : addDays(last, -119);
        try {
            const t = await api("GET", "/risk/trend", { params: { start: first, end: last } });
            clear(trendBox).appendChild(lineChart(
                t.data.days.map((d) => ({ x: d.day, y: d.fraud_rate_pct })),
                { shade: { from: start, to: end }, yLabel: "Fraud rate %", name: "Daily fraud rate" }));
            trendBox.appendChild(h("p", { class: "muted small" }, "Shaded area = selected period."));
        } catch (e) { clear(trendBox).appendChild(h("p", { class: "muted" }, e.message)); }
    }

    async function loadDrivers() {
        clear(driverBox).appendChild(h("p", { class: "muted" }, "Loading…"));
        try {
            const d = await api("GET", "/risk/drivers", { params: { dimension: select.value, start, end } });
            const g = d.data.groups;
            clear(driverBox).append(
                barChart(g.map((x) => String(x.value)), [
                    { name: "Selected period", values: g.map((x) => x.fraud_rate_pct) },
                    { name: "Baseline (14 days before)", values: g.map((x) => x.baseline_fraud_rate_pct) },
                ], { yLabel: "Fraud rate %" }),
                table([
                    { key: "value", label: DIMENSIONS[select.value] },
                    { key: "transactions", label: "Transactions", class: "num", fmt: fmtInt },
                    { key: "fraud_count", label: "Fraud", class: "num", fmt: fmtInt },
                    { key: "fraud_rate_pct", label: "Fraud rate %", class: "num" },
                    { key: "baseline_fraud_rate_pct", label: "Baseline %", class: "num" },
                    { key: "low_sample", label: "Note", fmt: (v) => (v ? "low sample" : "") },
                ], g));
        } catch (e) { clear(driverBox).appendChild(h("p", { class: "muted" }, e.message)); toast(e.message, "bad"); }
    }
    select.addEventListener("change", loadDrivers);
    await Promise.all([loadTrend(), loadDrivers()]);
}