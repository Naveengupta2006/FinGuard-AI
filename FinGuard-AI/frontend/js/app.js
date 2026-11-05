// FinGuard AI single-page app: login, shell (sidebar + date range), hash router.
import { api, clearSession, getSession, setSession } from "./api.js";
import { addDays, daysInclusive } from "./dates.js";
import { clear, errorBox, h, toast } from "./ui.js";
import * as overview from "./pages/overview.js";
import * as transactions from "./pages/transactions.js";
import * as investigations from "./pages/investigations.js";
import * as assistant from "./pages/assistant.js";

const PAGES = {
    overview: { label: "Overview", mod: overview },
    transactions: { label: "Transactions", mod: transactions },
    investigations: { label: "Investigations", mod: investigations },
    assistant: { label: "Policy assistant", mod: assistant },
};
const WRITE_ROLES = new Set(["analyst", "admin"]);
const state = { coverage: null, range: null };
const appRoot = () => document.getElementById("app");

function parseHash() {
    const [page, param] = location.hash.replace(/^#\/?/, "").split("/");
    return { page: PAGES[page] ? page : "overview", param: param || null };
}

// ---------------- login ----------------
export function showLogin(message = "") {
    const err = h("div", {});
    const user = h("input", { type: "text", id: "username", autocomplete: "username", required: true, "aria-label": "Username" });
    const pass = h("input", { type: "password", id: "password", autocomplete: "current-password", required: true, "aria-label": "Password" });
    const btn = h("button", { type: "submit", class: "btn btn-primary" }, "Log in");
    const form = h("form", { class: "stack" },
        h("label", {}, "Username", user), h("label", {}, "Password", pass), err, btn);
    if (message) err.appendChild(h("div", { class: "alert alert-warn" }, message));

    form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        btn.disabled = true;
        clear(err);
        try {
            const r = await api("POST", "/auth/login", { body: { username: user.value, password: pass.value } });
            setSession({ token: r.access_token, role: r.role, username: user.value });
            await showShell();
        } catch (e) {
            err.appendChild(errorBox(e.status === 401 ? "Login failed: invalid username or password." : e.message));
            btn.disabled = false;
            pass.value = "";
        }
    });

    const switchReg = h("p", { class: "muted small" },
        "Don't have an account? ",
        h("button", { type: "button", class: "btn-link", onClick: () => showRegister() }, "Create account")
    );

    clear(appRoot()).appendChild(h("main", { class: "login" },
        h("div", { class: "login-card" },
            h("div", { class: "logo" }, "🛡️"), h("h1", {}, "FinGuard AI"),
            h("p", { class: "muted" }, "Autonomous Financial Risk Intelligence Platform"),
            form,
            switchReg,
            h("p", { class: "muted small" }, "Educational decision-support on a synthetic dataset."))));
}

// ---------------- register ----------------
export function showRegister(message = "") {
    const err = h("div", {});
    const user = h("input", { type: "text", id: "reg-username", autocomplete: "username", required: true, "aria-label": "Username", placeholder: "3-50 characters" });
    const pass = h("input", { type: "password", id: "reg-password", autocomplete: "new-password", required: true, "aria-label": "Password", placeholder: "Min 10 characters" });
    const role = h("select", { id: "reg-role", "aria-label": "Role" },
        h("option", { value: "analyst" }, "Analyst (Full access)"),
        h("option", { value: "viewer" }, "Viewer (Read only)"));
    const btn = h("button", { type: "submit", class: "btn btn-primary" }, "Create account");
    const form = h("form", { class: "stack" },
        h("label", {}, "Username", user),
        h("label", {}, "Password", pass),
        h("label", {}, "Role", role),
        err, btn);
    if (message) err.appendChild(h("div", { class: "alert alert-warn" }, message));

    form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        btn.disabled = true;
        clear(err);
        try {
            const r = await api("POST", "/auth/register", {
                body: { username: user.value.trim(), password: pass.value, role: role.value }
            });
            setSession({ token: r.access_token, role: r.role, username: user.value.trim() });
            toast("Account created! Welcome, " + user.value.trim(), "good");
            await showShell();
        } catch (e) {
            err.appendChild(errorBox(e.message || "Registration failed."));
            btn.disabled = false;
        }
    });

    const switchLogin = h("p", { class: "muted small" },
        "Already have an account? ",
        h("button", { type: "button", class: "btn-link", onClick: () => showLogin() }, "Log in")
    );

    clear(appRoot()).appendChild(h("main", { class: "login" },
        h("div", { class: "login-card" },
            h("div", { class: "logo" }, "🛡️"), h("h1", {}, "FinGuard AI"),
            h("p", { class: "muted" }, "Create an account"),
            form,
            switchLogin,
            h("p", { class: "muted small" }, "Educational decision-support on a synthetic dataset."))));
}

// ---------------- shell ----------------
export async function showShell() {
    const session = getSession();
    if (!session) return showLogin();
    let cov;
    try { cov = (await api("GET", "/data/coverage")).data; } catch (e) {
        if (getSession()) clear(appRoot()).appendChild(errorBox(e.message));
        return;
    }
    if (!cov.last_date) { clear(appRoot()).appendChild(errorBox("The database has no transactions yet.")); return; }
    state.coverage = cov;
    state.range = { start: addDays(cov.last_date, -6) < cov.first_date ? cov.first_date : addDays(cov.last_date, -6), end: cov.last_date };

    const startIn = h("input", { type: "date", id: "range-start", value: state.range.start, min: cov.first_date, max: cov.last_date, "aria-label": "Start date" });
    const endIn = h("input", { type: "date", id: "range-end", value: state.range.end, min: cov.first_date, max: cov.last_date, "aria-label": "End date" });
    const onRange = () => {
        const s = startIn.value, e = endIn.value;
        if (!s || !e || s > e || daysInclusive(s, e) > 120) {
            toast("Choose a valid range of at most 120 days.", "bad");
            startIn.value = state.range.start; endIn.value = state.range.end;
            return;
        }
        state.range = { start: s, end: e };
        renderRoute();
    };
    startIn.addEventListener("change", onRange);
    endIn.addEventListener("change", onRange);

    const nav = h("nav", { "aria-label": "Main" }, Object.entries(PAGES).map(([key, p]) =>
        h("a", { href: `#/${key}`, "data-page": key }, p.label)));
    const logout = h("button", { class: "btn btn-ghost", id: "logout" }, "Log out");
    logout.addEventListener("click", () => { clearSession(); assistant.resetChat(); showLogin(); });

    clear(appRoot()).appendChild(h("div", { class: "shell" },
        h("aside", { class: "sidebar" },
            h("div", { class: "brand" }, "🛡️ FinGuard AI"),
            nav,
            h("div", { class: "range" }, h("div", { class: "label" }, "Period"),
                h("label", {}, "From", startIn), h("label", {}, "To", endIn)),
            h("div", { class: "user" }, h("strong", {}, session.username), h("span", { class: "muted small" }, `Role: ${session.role}`), logout),
            h("p", { class: "muted small" }, "Educational decision-support on a synthetic dataset. No automated actions are taken; consequential actions need human approval.")),
        h("main", { id: "page", class: "content" })));

    await renderRoute();
}

export async function renderRoute() {
    const page = document.getElementById("page");
    const session = getSession();
    if (!page || !session) return;
    const { page: key, param } = parseHash();
    document.querySelectorAll("nav a").forEach((a) => {
        if (a.dataset.page === key) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    const ctx = { range: state.range, coverage: state.coverage, role: session.role, username: session.username, canWrite: WRITE_ROLES.has(session.role) };
    try { await PAGES[key].mod.render(page, ctx, param); } catch (e) { clear(page).appendChild(errorBox(e.message)); }
}

function bindGlobals() {
    if (window.__fgBound) return;       // sirf ek baar listeners lagao
    window.__fgBound = true;
    window.addEventListener("hashchange", () => { if (document.getElementById("page")) renderRoute(); });
    window.addEventListener("fg:logout", (ev) => { assistant.resetChat(); showLogin(ev.detail || ""); });
}

export async function boot() {
    bindGlobals();
    return getSession() ? showShell() : showLogin();
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
