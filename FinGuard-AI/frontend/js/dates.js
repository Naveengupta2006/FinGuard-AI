// Date helpers (UTC arithmetic: timezone ki wajah se din aage-peeche nahi hote)
const toUtc = (iso) => {
    const [y, m, d] = iso.split("-").map(Number);
    return Date.UTC(y, m - 1, d);
};
const fmt = (ms) => new Date(ms).toISOString().slice(0, 10);

export const addDays = (iso, n) => fmt(toUtc(iso) + n * 86400000);
export const daysInclusive = (start, end) => Math.round((toUtc(end) - toUtc(start)) / 86400000) + 1;

// Same length ka pichla period
export function previousPeriod(start, end) {
    const n = daysInclusive(start, end);
    const bEnd = addDays(start, -1);
    return { start: addDays(bEnd, -(n - 1)), end: bEnd };
}