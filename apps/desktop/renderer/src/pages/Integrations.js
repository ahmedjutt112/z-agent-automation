import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * Integrations page — master prompt §54.
 * Lists OAuth providers (Google / GitHub / Facebook) with Connect buttons,
 * plus the messaging integrations (Email / WhatsApp / Telegram / Discord)
 * with a status badge and a send-message form for each.
 */
import { useEffect, useState } from "react";
import { api } from "../lib/api";
export function Integrations() {
    const [oauth, setOauth] = useState([]);
    const [integrations, setIntegrations] = useState([]);
    const [status, setStatus] = useState("loading");
    const [error, setError] = useState("");
    async function refresh() {
        setStatus("loading");
        setError("");
        try {
            const [oauthResp, integResp] = await Promise.all([
                api.oauth.status(),
                api.integrations.list(),
            ]);
            setOauth(oauthResp.providers);
            setIntegrations(integResp.integrations);
            setStatus("ready");
        }
        catch (e) {
            setError(String(e));
            setStatus("error");
        }
    }
    useEffect(() => {
        refresh();
    }, []);
    async function handleConnect(provider) {
        try {
            const { authorization_url } = await api.oauth.start(provider);
            window.open(authorization_url, "_blank", "noopener,noreferrer");
        }
        catch (e) {
            setError(String(e));
        }
    }
    async function handleDisconnect(provider) {
        try {
            await api.oauth.disconnect(provider);
            await refresh();
        }
        catch (e) {
            setError(String(e));
        }
    }
    const findIntegration = (name) => integrations.find((i) => i.name === name);
    return (_jsxs("div", { className: "space-y-6", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-2xl font-semibold", children: "Integrations" }), _jsx("p", { className: "text-zinc-400 mt-1", children: "Connect OAuth providers and configure messaging channels." })] }), status === "error" && (_jsx("div", { className: "bg-red-900/20 border border-red-700 rounded-lg p-3 text-sm text-red-300", children: error })), _jsx(Section, { title: "OAuth Providers", children: _jsxs("div", { className: "grid grid-cols-1 md:grid-cols-3 gap-3", children: [oauth.map((p) => (_jsx(OAuthCard, { provider: p, onConnect: () => handleConnect(p.provider), onDisconnect: () => handleDisconnect(p.provider) }, p.provider))), oauth.length === 0 && status === "ready" && (_jsx("div", { className: "text-zinc-500 text-sm col-span-3", children: "No OAuth providers configured." }))] }) }), _jsxs(Section, { title: "Email (SMTP / IMAP)", children: [_jsx(IntegrationCard, { entry: findIntegration("email") }), _jsx(EmailForm, { onSent: refresh })] }), _jsxs(Section, { title: "WhatsApp (Business API)", children: [_jsx(IntegrationCard, { entry: findIntegration("whatsapp") }), _jsx(WhatsAppForm, {})] }), _jsxs(Section, { title: "Telegram (Bot API)", children: [_jsx(IntegrationCard, { entry: findIntegration("telegram") }), _jsx(TelegramForm, {})] }), _jsxs(Section, { title: "Discord (Bot API)", children: [_jsx(IntegrationCard, { entry: findIntegration("discord") }), _jsx(DiscordForm, {})] })] }));
}
// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function Section({ title, children }) {
    return (_jsxs("section", { className: "bg-zinc-900 rounded-lg border border-zinc-800 p-4", children: [_jsx("h2", { className: "text-sm uppercase tracking-wider text-zinc-500 mb-3", children: title }), _jsx("div", { className: "space-y-3", children: children })] }));
}
function StatusBadge({ configured, connected }) {
    const isOk = connected ?? configured;
    return (_jsx("span", { className: `inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${isOk
            ? "bg-emerald-500/20 text-emerald-300 border border-emerald-700"
            : "bg-red-500/20 text-red-300 border border-red-700"}`, children: isOk ? (connected ? "Connected" : "Configured") : "Not configured" }));
}
function OAuthCard({ provider, onConnect, onDisconnect, }) {
    const label = provider.provider[0].toUpperCase() + provider.provider.slice(1);
    return (_jsxs("div", { className: "bg-zinc-950 border border-zinc-800 rounded-lg p-4 flex flex-col gap-3", children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsx("div", { className: "font-medium", children: label }), _jsx(StatusBadge, { configured: provider.configured, connected: provider.connected })] }), _jsxs("div", { className: "flex gap-2", children: [_jsx("button", { onClick: onConnect, disabled: !provider.configured, className: "flex-1 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed rounded px-3 py-1.5 text-sm", children: provider.connected ? "Reconnect" : "Connect" }), provider.connected && (_jsx("button", { onClick: onDisconnect, className: "bg-red-900/40 hover:bg-red-800 text-red-200 rounded px-3 py-1.5 text-sm", children: "Disconnect" }))] }), !provider.configured && (_jsxs("div", { className: "text-xs text-zinc-500", children: ["Set the ", provider.provider.toUpperCase(), "_OAUTH_CLIENT_ID env vars to enable."] }))] }));
}
function IntegrationCard({ entry }) {
    if (!entry) {
        return (_jsx("div", { className: "text-sm text-zinc-500", children: "Loading status\u2026" }));
    }
    return (_jsxs("div", { className: "flex items-center justify-between text-sm", children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsx("span", { className: "capitalize", children: entry.name }), _jsx(StatusBadge, { configured: entry.configured })] }), _jsx("span", { className: "text-xs text-zinc-500", children: entry.status })] }));
}
function EmailForm({ onSent }) {
    const [to, setTo] = useState("");
    const [subject, setSubject] = useState("");
    const [body, setBody] = useState("");
    const [busy, setBusy] = useState(false);
    const [msg, setMsg] = useState("");
    async function submit(e) {
        e.preventDefault();
        setBusy(true);
        setMsg("");
        try {
            const res = await api.integrations.sendEmail(to, subject, body);
            setMsg(res.sent
                ? `Sent to ${res.to.join(", ")}${res.mock ? " (mock)" : ""}`
                : "Failed to send");
            setTo("");
            setSubject("");
            setBody("");
            onSent?.();
        }
        catch (e) {
            setMsg(`Error: ${String(e)}`);
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsxs("form", { onSubmit: submit, className: "grid grid-cols-1 gap-2", children: [_jsx("input", { className: "bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm", placeholder: "to@example.com", value: to, onChange: (e) => setTo(e.target.value), required: true }), _jsx("input", { className: "bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm", placeholder: "Subject", value: subject, onChange: (e) => setSubject(e.target.value), required: true }), _jsx("textarea", { className: "bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm min-h-[80px]", placeholder: "Body", value: body, onChange: (e) => setBody(e.target.value), required: true }), _jsxs("div", { className: "flex items-center gap-3", children: [_jsx("button", { type: "submit", disabled: busy, className: "bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-4 py-1.5 text-sm", children: busy ? "Sending…" : "Send Email" }), msg && _jsx("span", { className: "text-xs text-zinc-400", children: msg })] })] }));
}
function WhatsAppForm() {
    const [to, setTo] = useState("");
    const [message, setMessage] = useState("");
    const [busy, setBusy] = useState(false);
    const [msg, setMsg] = useState("");
    async function submit(e) {
        e.preventDefault();
        setBusy(true);
        setMsg("");
        try {
            const res = await api.integrations.sendWhatsApp(to, message);
            setMsg(`Sent (id=${res.message_id}${res.mock ? ", mock" : ""})`);
            setTo("");
            setMessage("");
        }
        catch (e) {
            setMsg(`Error: ${String(e)}`);
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsxs("form", { onSubmit: submit, className: "grid grid-cols-1 gap-2", children: [_jsx("input", { className: "bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm", placeholder: "15551234567 (international, no +)", value: to, onChange: (e) => setTo(e.target.value), required: true }), _jsx("textarea", { className: "bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm min-h-[60px]", placeholder: "Message body", value: message, onChange: (e) => setMessage(e.target.value), required: true }), _jsxs("div", { className: "flex items-center gap-3", children: [_jsx("button", { type: "submit", disabled: busy, className: "bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-4 py-1.5 text-sm", children: busy ? "Sending…" : "Send WhatsApp" }), msg && _jsx("span", { className: "text-xs text-zinc-400", children: msg })] })] }));
}
function TelegramForm() {
    const [chatId, setChatId] = useState("");
    const [text, setText] = useState("");
    const [busy, setBusy] = useState(false);
    const [msg, setMsg] = useState("");
    async function submit(e) {
        e.preventDefault();
        setBusy(true);
        setMsg("");
        try {
            const res = await api.integrations.sendTelegram(chatId, text);
            setMsg(`Sent (id=${res.message_id}${res.mock ? ", mock" : ""})`);
            setChatId("");
            setText("");
        }
        catch (e) {
            setMsg(`Error: ${String(e)}`);
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsxs("form", { onSubmit: submit, className: "grid grid-cols-1 gap-2", children: [_jsx("input", { className: "bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm", placeholder: "Chat ID or @channelname", value: chatId, onChange: (e) => setChatId(e.target.value), required: true }), _jsx("textarea", { className: "bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm min-h-[60px]", placeholder: "Text (HTML parse mode by default)", value: text, onChange: (e) => setText(e.target.value), required: true }), _jsxs("div", { className: "flex items-center gap-3", children: [_jsx("button", { type: "submit", disabled: busy, className: "bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-4 py-1.5 text-sm", children: busy ? "Sending…" : "Send Telegram" }), msg && _jsx("span", { className: "text-xs text-zinc-400", children: msg })] })] }));
}
function DiscordForm() {
    const [channelId, setChannelId] = useState("");
    const [content, setContent] = useState("");
    const [busy, setBusy] = useState(false);
    const [msg, setMsg] = useState("");
    async function submit(e) {
        e.preventDefault();
        setBusy(true);
        setMsg("");
        try {
            const res = await api.integrations.sendDiscord(channelId, content);
            setMsg(`Sent (id=${res.message_id}${res.mock ? ", mock" : ""})`);
            setChannelId("");
            setContent("");
        }
        catch (e) {
            setMsg(`Error: ${String(e)}`);
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsxs("form", { onSubmit: submit, className: "grid grid-cols-1 gap-2", children: [_jsx("input", { className: "bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm", placeholder: "Channel ID", value: channelId, onChange: (e) => setChannelId(e.target.value), required: true }), _jsx("textarea", { className: "bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm min-h-[60px]", placeholder: "Message content", value: content, onChange: (e) => setContent(e.target.value), required: true }), _jsxs("div", { className: "flex items-center gap-3", children: [_jsx("button", { type: "submit", disabled: busy, className: "bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-4 py-1.5 text-sm", children: busy ? "Sending…" : "Send Discord" }), msg && _jsx("span", { className: "text-xs text-zinc-400", children: msg })] })] }));
}
