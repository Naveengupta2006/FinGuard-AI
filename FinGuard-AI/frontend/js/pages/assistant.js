import { api } from "../api.js";
import { clear, h, pageHeader } from "../ui.js";

let messages = [];
export const resetChat = () => { messages = []; };
const INV_RE = /^INV-\d{3,6}$/;

export async function render(root, ctx) {
    const list = h("div", { class: "chat", "aria-live": "polite" });
    const input = h("input", { type: "text", id: "chat-input", maxlength: 500, placeholder: "Ask about a policy or procedure…", "aria-label": "Message" });
    const send = h("button", { type: "submit", class: "btn btn-primary" }, "Send");
    const toggle = ctx.canWrite ? h("input", { type: "checkbox", id: "run-investigation" }) : null;
    const form = h("form", { class: "chat-form" }, input, send);

    function draw() {
        clear(list);
        if (!messages.length) {
            list.appendChild(h("p", { class: "muted" }, "Try: “Who approves blocking a customer account?” or “What does probability of default mean?”"));
        }
        for (const m of messages) {
            const body = [h("div", {}, m.content)];
            if (m.citations && m.citations.length) {
                body.push(h("details", {}, h("summary", {}, `Citations (${m.citations.length})`), h("ul", {}, m.citations.map((c) => h("li", {}, c)))));
            }
            if (m.investigationId && INV_RE.test(m.investigationId)) {
                body.push(h("a", { href: `#/investigations/${m.investigationId}` }, `Open ${m.investigationId} →`));
            }
            list.appendChild(h("div", { class: `bubble bubble-${m.role}` }, ...body));
        }
        list.scrollTop = list.scrollHeight;
    }

    form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const text = input.value.trim();
        if (text.length < 3) return;
        input.value = ""; input.disabled = send.disabled = true;
        messages.push({ role: "user", content: text });
        draw();
        try {
            if (ctx.canWrite) {
                const body = { question: text };
                if (toggle && toggle.checked) body.date_range = ctx.range;
                const r = await api("POST", "/agent/chat", { body, timeout: 300000 });
                messages.push(r.mode === "investigation"
                    ? { role: "assistant", content: r.reply, investigationId: r.investigation_id }
                    : { role: "assistant", content: r.reply, citations: r.citations });
            } else {
                const r = await api("POST", "/policies/search", { body: { query: text, k: 3 } });
                messages.push(r.results.length
                    ? { role: "assistant", content: r.results[0].text, citations: r.results.map((x) => x.citation) }
                    : { role: "assistant", content: "No relevant policy passage was found." });
            }
        } catch (e) { messages.push({ role: "assistant", content: `Error: ${e.message}` }); }
        input.disabled = send.disabled = false;
        draw();
        input.focus();
    });

    clear(root).append(
        pageHeader("Policy assistant", "Answers come from retrieved policy text and are cited. They are reference data, not advice."),
        toggle ? h("label", { class: "check" }, toggle, ` Run a data investigation for ${ctx.range.start} to ${ctx.range.end} instead`) : null,
        list, form);
    draw();
}