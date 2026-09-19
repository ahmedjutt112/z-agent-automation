import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * AI Models page — master prompt §6 (52 AI providers).
 *
 * Lists every provider in the registry with a credential badge (green when
 * an API key has been stored, red otherwise) and an OpenAI-compatible
 * badge. Clicking a provider opens a detail panel with its models, test
 * connection button, sync button, and credential add/remove form.
 *
 * Top-level: Sync All Models button + default provider/model selectors.
 */
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";
export function AIModels() {
    const mockMode = useStore((s) => s.mockMode);
    const [providers, setProviders] = useState([]);
    const [defaultProvider, setDefaultProvider] = useState("");
    const [defaultModel, setDefaultModel] = useState("");
    const [selected, setSelected] = useState(null);
    const [models, setModels] = useState([]);
    const [creds, setCreds] = useState([]);
    const [status, setStatus] = useState("loading");
    const [error, setError] = useState("");
    const [syncing, setSyncing] = useState(false);
    const [syncMessage, setSyncMessage] = useState("");
    async function refresh() {
        setStatus("loading");
        setError("");
        try {
            const [p, c] = await Promise.all([
                api.aiModels.listProviders(),
                api.aiModels.listCredentials(),
            ]);
            setProviders(p.providers);
            setDefaultProvider(p.default_provider);
            setDefaultModel(p.default_model);
            setCreds(c.credentials);
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
    async function selectProvider(p) {
        setSelected(p);
        setModels([]);
        try {
            const r = await api.aiModels.list(p.name);
            setModels(r.models ?? []);
        }
        catch (e) {
            setError(String(e));
        }
    }
    async function syncAll() {
        setSyncing(true);
        setError("");
        setSyncMessage("");
        try {
            const r = await api.aiModels.sync();
            const total = Object.values(r.synced).reduce((a, b) => a + b, 0);
            setSyncMessage(`Synced ${total} models across ${Object.keys(r.synced).length} providers.`);
            if (selected) {
                await selectProvider(selected);
            }
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setSyncing(false);
        }
    }
    async function testProvider(name) {
        setError("");
        try {
            const r = await api.aiModels.testProvider(name);
            setSyncMessage(`${name}: ${r.message}`);
        }
        catch (e) {
            setError(String(e));
        }
    }
    async function syncOne(name) {
        setError("");
        try {
            const r = await api.aiModels.sync(name);
            setSyncMessage(`Synced ${r.synced[name] ?? 0} models from ${name}.`);
            await selectProvider(selected ?? { name });
        }
        catch (e) {
            setError(String(e));
        }
    }
    async function addCredential(service) {
        const value = window.prompt(`Enter API key for ${service}:`, "");
        if (!value)
            return;
        try {
            await api.aiModels.addCredential(service, value);
            await refresh();
            if (selected)
                await selectProvider(selected);
        }
        catch (e) {
            setError(String(e));
        }
    }
    async function removeCredential(service) {
        if (!window.confirm(`Remove credential for ${service}?`))
            return;
        try {
            await api.aiModels.removeCredential(service);
            await refresh();
            if (selected)
                await selectProvider(selected);
        }
        catch (e) {
            setError(String(e));
        }
    }
    return (_jsxs("div", { className: "space-y-6", children: [_jsxs("div", { className: "flex items-end justify-between", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-2xl font-semibold", children: "AI Models" }), _jsx("p", { className: "text-zinc-400 mt-1", children: "Configure 52 AI providers, store API keys in the OS keyring, sync models." })] }), _jsx("div", { className: "flex gap-2", children: _jsx("button", { onClick: syncAll, disabled: syncing, className: "bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 rounded px-3 py-1.5 text-sm", children: syncing ? "Syncing..." : "Sync All Models" }) })] }), mockMode && (_jsx("div", { className: "bg-amber-900/20 border border-amber-700 rounded-lg p-3 text-sm text-amber-300", children: "Sync runs in mock mode \u2014 local providers are skipped and providers without a credential return 0." })), error && (_jsx("div", { className: "bg-red-900/20 border border-red-700 rounded-lg p-3 text-sm text-red-300", children: error })), syncMessage && (_jsx("div", { className: "bg-zinc-800 border border-zinc-700 rounded-lg p-3 text-sm text-zinc-200", children: syncMessage })), _jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg p-4 grid grid-cols-2 gap-4", children: [_jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Default Provider" }), _jsxs("div", { className: "mt-1 text-sm font-medium", children: [defaultProvider, " ", _jsx("span", { className: "text-xs text-zinc-500", children: "(read-only \u2014 set via env var)" })] })] }), _jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Default Model" }), _jsxs("div", { className: "mt-1 text-sm font-medium", children: [defaultModel, " ", _jsx("span", { className: "text-xs text-zinc-500", children: "(read-only \u2014 set via env var)" })] })] })] }), _jsxs("div", { className: "grid grid-cols-12 gap-4", children: [_jsx("div", { className: "col-span-7", children: _jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg", children: [_jsxs("div", { className: "px-4 py-3 border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500", children: ["Providers (", providers.length, ")"] }), _jsx("div", { className: "grid grid-cols-2 gap-2 p-3 max-h-[600px] overflow-y-auto", children: status === "loading" ? (_jsx("div", { className: "col-span-2 text-center py-8 text-zinc-500 text-sm", children: "Loading..." })) : (providers.map((p) => (_jsxs("button", { onClick: () => selectProvider(p), className: `text-left bg-zinc-950 border rounded p-3 hover:border-zinc-600 transition-colors ${selected?.name === p.name ? "border-zinc-500" : "border-zinc-800"}`, children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsx("span", { className: "text-sm font-medium truncate", children: p.display_name }), _jsx("span", { className: `inline-flex items-center px-2 py-0.5 rounded text-xs ${p.has_credential
                                                            ? "bg-emerald-500/20 text-emerald-300"
                                                            : "bg-red-500/20 text-red-300"}`, children: p.has_credential ? "Key" : "No key" })] }), _jsx("div", { className: "text-xs text-zinc-500 mt-1 font-mono truncate", children: p.name }), p.openai_compatible && (_jsx("span", { className: "inline-block mt-1 text-xs text-blue-300 bg-blue-500/10 border border-blue-700 rounded px-1.5 py-0.5", children: "OpenAI-compat" }))] }, p.name)))) })] }) }), _jsx("div", { className: "col-span-5", children: selected ? (_jsx(ProviderDetail, { provider: selected, models: models, creds: creds, onTest: () => testProvider(selected.name), onSync: () => syncOne(selected.name), onAddKey: () => selected.env_key && addCredential(selected.env_key), onRemoveKey: () => selected.env_key && removeCredential(selected.env_key) })) : (_jsx("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg p-8 text-center text-zinc-500 text-sm", children: "Select a provider to view details." })) })] })] }));
}
function ProviderDetail({ provider, models, creds, onTest, onSync, onAddKey, onRemoveKey, }) {
    const cred = creds.find((c) => c.service === provider.env_key);
    const hasKey = !!cred?.has_credential;
    return (_jsxs("div", { className: "space-y-3", children: [_jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg p-4", children: [_jsxs("div", { className: "flex items-center justify-between mb-3", children: [_jsxs("div", { children: [_jsx("div", { className: "text-sm font-medium", children: provider.display_name }), _jsx("div", { className: "text-xs text-zinc-500 font-mono", children: provider.name })] }), _jsx("span", { className: `inline-flex items-center px-2 py-0.5 rounded text-xs ${hasKey
                                    ? "bg-emerald-500/20 text-emerald-300"
                                    : "bg-red-500/20 text-red-300"}`, children: hasKey ? "Has credential" : "No credential" })] }), _jsxs("div", { className: "space-y-2 text-xs", children: [provider.base_url && (_jsxs("div", { children: [_jsx("span", { className: "text-zinc-500", children: "Base URL: " }), _jsx("span", { className: "font-mono text-zinc-300 break-all", children: provider.base_url })] })), provider.env_key && (_jsxs("div", { children: [_jsx("span", { className: "text-zinc-500", children: "Env key: " }), _jsx("span", { className: "font-mono text-zinc-300", children: provider.env_key })] })), _jsxs("div", { children: [_jsx("span", { className: "text-zinc-500", children: "Default model: " }), _jsx("span", { className: "font-mono text-zinc-300", children: provider.default_model })] }), provider.notes && (_jsx("div", { className: "text-zinc-400 italic pt-1", children: provider.notes }))] }), _jsxs("div", { className: "mt-3 flex gap-2 flex-wrap", children: [_jsx("button", { onClick: onTest, className: "bg-zinc-700 hover:bg-zinc-600 rounded px-3 py-1.5 text-xs", children: "Test Connection" }), _jsx("button", { onClick: onSync, className: "bg-zinc-700 hover:bg-zinc-600 rounded px-3 py-1.5 text-xs", children: "Sync Models" }), provider.env_key && !hasKey && (_jsx("button", { onClick: onAddKey, className: "bg-emerald-700 hover:bg-emerald-600 rounded px-3 py-1.5 text-xs", children: "Add API Key" })), provider.env_key && hasKey && (_jsx("button", { onClick: onRemoveKey, className: "bg-red-900/40 hover:bg-red-800 text-red-200 rounded px-3 py-1.5 text-xs", children: "Remove API Key" }))] })] }), _jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg", children: [_jsxs("div", { className: "px-4 py-2 border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500", children: ["Models (", models.length, ")"] }), _jsx("div", { className: "divide-y divide-zinc-800 max-h-96 overflow-y-auto", children: models.length === 0 ? (_jsx("div", { className: "px-4 py-8 text-center text-zinc-500 text-sm", children: "No models synced. Click \"Sync Models\" to fetch." })) : (models.map((m) => (_jsxs("div", { className: "px-4 py-2 flex items-center justify-between", children: [_jsxs("div", { children: [_jsx("div", { className: "text-sm font-mono", children: m.model_id }), _jsx("div", { className: "text-xs text-zinc-500 mt-0.5", children: m.display_name })] }), _jsxs("div", { className: "flex gap-2", children: [m.supports_vision && (_jsx("span", { className: "text-xs text-purple-300 bg-purple-500/10 border border-purple-700 rounded px-1.5 py-0.5", children: "vision" })), m.supports_reasoning && (_jsx("span", { className: "text-xs text-blue-300 bg-blue-500/10 border border-blue-700 rounded px-1.5 py-0.5", children: "reasoning" })), _jsxs("span", { className: "text-xs text-zinc-500", children: [m.max_tokens.toLocaleString(), " tok"] })] })] }, m.id)))) })] })] }));
}
