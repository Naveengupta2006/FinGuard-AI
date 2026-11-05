import { api } from "../api.js";
import { badge, card, clear, fmtDateTime, fmtInt, fmtMoney, h, loading, pageHeader, showError, table } from "../ui.js";

const CATEGORIES = ["", "grocery", "fuel", "restaurant", "electronics", "travel", "fashion", "utilities", "entertainment", "jewelry", "gift_cards"];
const BAND_TONE = { HIGH: "bad", MEDIUM: "warn", LOW: "good" };

export async function render(root, ctx) {
    const { start, end } = ctx.range;
    let page = 1;
    const results = h("div", {});
    const f = {
        category: h("select", { "aria-label": "Category" }, CATEGORIES.map((c) => h("option", { value: c }, c || "All categories"))),
        country: h("input", { type: "text", maxlength: 2, placeholder: "e.g. NG", "aria-label": "Country" }),
        band: h("select", { "aria-label": "Risk band" }, ["", "HIGH", "MEDIUM", "LOW"].map((b) => h("option", { value: b }, b || "All bands"))),
        minAmount: h("input", { type: "number", min: 0, step: 100, placeholder: "Min amount", "aria-label": "Minimum amount" }),
        size: h("select", { "aria-label": "Rows per page" }, [20, 50, 100].map((n) => h("option", { value: n }, `${n} rows`))),
    };
    const form = h("form", { class: "toolbar wrap" },
        f.category, f.country, f.band, f.minAmount, f.size, h("button", { type: "submit", class: "btn" }, "Search"));

    async function load() {
        loading(results);
        const size = Number(f.size.value);
        try {
            const res = await api("GET", "/transactions", {
                params: {
                    start, end, limit: size, offset: (page - 1) * size,
                    merchant_category: f.category.value, country: f.country.value.trim().toUpperCase(),
                    risk_band: f.band.value, min_amount: f.minAmount.value,
                }
            });
            const d = res.data, pages = Math.max(1, Math.ceil(d.total / size));
            clear(results).append(
                h("p", { class: "muted" }, `${fmtInt(d.total)} matching transactions. Page ${page} of ${pages}.`),
                table([
                    { key: "transaction_id", label: "Transaction" },
                    { key: "timestamp", label: "Time", fmt: fmtDateTime },
                    { key: "customer_id", label: "Customer" },
                    { key: "amount", label: "Amount", class: "num", fmt: fmtMoney },
                    { key: "merchant_category", label: "Category" },
                    { key: "country", label: "Country" },
                    { key: "channel", label: "Channel" },
                    { key: "device_type", label: "Device" },
                    { key: "risk_band", label: "Risk", fmt: (v, r) => (v ? badge(`${v} ${r.risk_score}`, BAND_TONE[v]) : "not scored") },
                    { key: "is_fraud", label: "Fraud", fmt: (v) => (v ? badge("fraud", "bad") : "") },
                ], d.transactions, { empty: "No transactions match these filters." }),
                h("div", { class: "toolbar" },
                    h("button", { class: "btn btn-ghost", disabled: page <= 1, onclick: () => { page -= 1; load(); } }, "← Previous"),
                    h("button", { class: "btn btn-ghost", disabled: page >= pages, onclick: () => { page += 1; load(); } }, "Next →")),
                ...res.limitations.map((l) => h("p", { class: "muted small" }, l)));
        } catch (e) { showError(results, e); }
    }

    form.addEventListener("submit", (ev) => { ev.preventDefault(); page = 1; load(); });
    clear(root).append(pageHeader("Transactions", `${start} to ${end}`), card(null, form), results);
    await load();
}