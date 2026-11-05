// Dependency-free SVG charts. Colors presentation attributes se (light default), CSS dark mode mein override karta hai.
import { h } from "./ui.js";

const COLORS = ["#2563eb", "#94a3b8"];
const W = 800, H = 280, M = { l: 52, r: 16, t: 24, b: 34 };

function niceMax(v) {
    if (!(v > 0)) return 1;
    const pow = 10 ** Math.floor(Math.log10(v));
    const n = v / pow;
    return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow;
}

function frame(yMax, yLabel) {
    const ticks = [0, 1, 2, 3, 4].map((i) => (yMax * i) / 4);
    const y = (v) => M.t + (H - M.t - M.b) * (1 - v / yMax);
    const grid = ticks.map((t) => h("g", {},
        h("line", { class: "grid", x1: M.l, x2: W - M.r, y1: y(t), y2: y(t), stroke: "#e2e8f0" }),
        h("text", { class: "axis", x: M.l - 8, y: y(t) + 4, "text-anchor": "end", fill: "#64748b" }, String(+t.toFixed(2)))));
    const label = yLabel ? h("text", { class: "axis", x: M.l + 6, y: 14, fill: "#64748b" }, yLabel) : null;
    return { y, grid, label };
}

const legend = (names) => h("div", { class: "legend" }, names.map((n, i) =>
    h("span", {}, h("i", { class: `dot series-${i}`, "data-i": i }), n)));

export function lineChart(points, { shade, yLabel, name = "Series" } = {}) {
    if (!points.length) return h("p", { class: "muted" }, "No data for this range.");
    const yMax = niceMax(Math.max(...points.map((p) => p.y)) * 1.1);
    const { y, grid, label } = frame(yMax, yLabel);
    const step = points.length > 1 ? (W - M.l - M.r) / (points.length - 1) : 0;
    const x = (i) => M.l + (points.length > 1 ? i * step : (W - M.l - M.r) / 2);

    let band = null;
    if (shade) {
        const idx = points.map((p, i) => (p.x >= shade.from && p.x <= shade.to ? i : -1)).filter((i) => i >= 0);
        if (idx.length) {
            const x0 = Math.max(M.l, x(idx[0]) - step / 2), x1 = Math.min(W - M.r, x(idx[idx.length - 1]) + step / 2);
            band = h("rect", { class: "shade", x: x0, y: M.t, width: Math.max(2, x1 - x0), height: H - M.t - M.b, fill: "#ef4444", "fill-opacity": 0.12 });
        }
    }
    const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.y).toFixed(1)}`).join(" ");
    const every = Math.ceil(points.length / 8);
    const xl = points.map((p, i) => (i % every === 0
        ? h("text", { class: "axis", x: x(i), y: H - 10, "text-anchor": "middle", fill: "#64748b" }, p.x.slice(5)) : null));
    const dots = points.map((p, i) => h("circle", { class: "pt", cx: x(i), cy: y(p.y), r: 3, fill: COLORS[0] },
        h("title", {}, `${p.x}: ${p.y}${yLabel ? "" : ""}`)));

    const svg = h("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${name} over time`, class: "chart" },
        grid, label, band, h("path", { class: "line series-0", d: path, fill: "none", stroke: COLORS[0], "stroke-width": 2 }), dots, xl);
    return h("div", {}, svg);
}

export function barChart(categories, series, { yLabel } = {}) {
    if (!categories.length) return h("p", { class: "muted" }, "No data for this selection.");
    const all = series.flatMap((s) => s.values);
    const yMax = niceMax(Math.max(...all) * 1.1);
    const { y, grid, label } = frame(yMax, yLabel);
    const slot = (W - M.l - M.r) / categories.length;
    const bw = Math.min(40, (slot * 0.7) / series.length);
    const bars = [], labels = [];
    categories.forEach((c, ci) => {
        const cx = M.l + slot * ci + slot / 2;
        series.forEach((s, si) => {
            const v = s.values[ci];
            const bx = cx - (bw * series.length) / 2 + bw * si;
            bars.push(h("rect", { class: `bar series-${si}`, x: bx, y: y(v), width: bw - 2, height: Math.max(0, y(0) - y(v)), fill: COLORS[si % COLORS.length] },
                h("title", {}, `${c} (${s.name}): ${v}`)));
        });
        labels.push(h("text", { class: "axis", x: cx, y: H - 10, "text-anchor": "middle", fill: "#64748b" },
            c.length > 12 ? c.slice(0, 11) + "…" : c));
    });
    const svg = h("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Grouped bar chart", class: "chart" }, grid, label, bars, labels);
    return h("div", {}, legend(series.map((s) => s.name)), svg);
}