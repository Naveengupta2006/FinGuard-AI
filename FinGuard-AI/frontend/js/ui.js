// Safe DOM helpers. Data hamesha textContent/text node se jaata hai, innerHTML kabhi nahi (XSS se bachao).
const SVG_TAGS = new Set(["svg", "g", "path", "line", "circle", "rect", "text", "title", "polyline"]);

function append(el, kids) {
    for (const c of kids.flat(Infinity)) {
        if (c === null || c === undefined || c === false) continue;
        el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
}

export function h(tag, props = {}, ...children) {
    const el = SVG_TAGS.has(tag)
        ? document.createElementNS("http://www.w3.org/2000/svg", tag)
        : document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
        if (v === null || v === undefined || v === false) continue;
        if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
        else if (k === "value") el.value = v;
        else if (k === "checked") el.checked = !!v;
        else el.setAttribute(k, v === true ? "" : String(v));
    }
    append(el, children);
    return el;
}

export function clear(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
    return el;
}

export const fmtInt = (n) => Number(n).toLocaleString("en-US");
export const fmtMoney = (n) => Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 });
export const fmtDateTime = (s) => String(s || "").replace("T", " ").slice(0, 16);
export const truncate = (s, n) => (s && s.length > n ? s.slice(0, n - 1) + "…" : s || "");

export function toast(message, tone = "info") {
    const box = document.getElementById("toasts");
    if (!box) return;
    const t = h("div", { class: `toast toast-${tone}`, role: "status" }, message);
    box.appendChild(t);
    setTimeout(() => t.remove(), 4500);
}

export const badge = (text, tone = "neutral") => h("span", { class: `badge badge-${tone}` }, text);

export const STATUS_TONE = {
    pending_human_review: "warn", approved: "good", rejected: "bad", no_evidence: "neutral",
};
export const statusBadge = (s) => badge(String(s).replaceAll("_", " "), STATUS_TONE[s] || "neutral");

export function kpi(label, value, { sub, tone = "" } = {}) {
    return h("div", { class: `kpi ${tone}` },
        h("div", { class: "kpi-label" }, label),
        h("div", { class: "kpi-value" }, value),
        sub ? h("div", { class: "kpi-sub" }, sub) : null);
}

export function card(title, ...body) {
    return h("section", { class: "card" }, title ? h("h3", { class: "card-title" }, title) : null, ...body);
}

export function table(columns, rows, { onRowClick, empty = "No data" } = {}) {
    if (!rows.length) return h("p", { class: "muted" }, empty);
    const head = h("tr", {}, columns.map((c) => h("th", { class: c.class || "" }, c.label)));
    const body = rows.map((r) => {
        const tr = h("tr", { class: onRowClick ? "clickable" : "" }, columns.map((c) => {
            const raw = r[c.key];
            const val = c.fmt ? c.fmt(raw, r) : raw;
            return h("td", { class: c.class || "" }, val === null || val === undefined ? "" : val);
        }));
        if (onRowClick) tr.addEventListener("click", () => onRowClick(r));
        return tr;
    });
    return h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, head), h("tbody", {}, body)));
}

export const loading = (root, text = "Loading…") =>
    clear(root).appendChild(h("div", { class: "loading" }, h("span", { class: "spinner" }), text));

export const errorBox = (message) => h("div", { class: "alert alert-bad", role: "alert" }, message);

export function showError(root, err) {
    clear(root).appendChild(errorBox(err && err.message ? err.message : String(err)));
}

export function pageHeader(title, subtitle, ...actions) {
    return h("header", { class: "page-header" },
        h("div", {}, h("h1", {}, title), subtitle ? h("p", { class: "muted" }, subtitle) : null),
        h("div", { class: "actions" }, ...actions));
}