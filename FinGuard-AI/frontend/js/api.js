// API client. Token sirf sessionStorage mein (tab band = logout). Har request par Bearer token.
const BASE = "/api/v1";
const KEY = "fg_session";

export class ApiError extends Error {
    constructor(message, status) {
        super(message);
        this.status = status;
    }
}

export function getSession() {
    try { return JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch { return null; }
}
export const setSession = (s) => sessionStorage.setItem(KEY, JSON.stringify(s));
export const clearSession = () => sessionStorage.removeItem(KEY);

function formatDetail(detail) {
    if (!detail) return "";
    if (Array.isArray(detail)) return detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
    return String(detail);
}

export async function api(method, path, { params, body, timeout = 30000 } = {}) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params || {})) {
        if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    }
    const url = BASE + path + (qs.toString() ? `?${qs}` : "");
    const headers = { Accept: "application/json" };
    const session = getSession();
    if (session && session.token) headers.Authorization = `Bearer ${session.token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout);
    let res;
    try {
        res = await fetch(url, {
            method, headers, signal: ctrl.signal,
            body: body !== undefined ? JSON.stringify(body) : undefined
        });
    } catch (e) {
        throw new ApiError(e.name === "AbortError" ? "The request timed out." : "Cannot reach the server. Is it running?", 0);
    } finally {
        clearTimeout(timer);
    }
    let data = null;
    try { data = await res.json(); } catch { /* khali body */ }
    if (!res.ok) {
        if (res.status === 401 && path !== "/auth/login") {
            clearSession();
            window.dispatchEvent(new CustomEvent("fg:logout", { detail: "Your session expired. Please log in again." }));
        }
        throw new ApiError(formatDetail(data && data.detail) || `Request failed (HTTP ${res.status})`, res.status);
    }
    return data;
}