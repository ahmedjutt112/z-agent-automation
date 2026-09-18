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

import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";

interface ProviderEntry {
  name: string;
  display_name: string;
  base_url: string | null;
  env_key: string | null;
  default_model: string;
  openai_compatible: boolean;
  supports_model_list: boolean;
  docs_url: string;
  notes: string;
  has_credential: boolean;
}

interface ModelEntry {
  id: string;
  model_id: string;
  display_name: string;
  provider_id: string;
  supports_vision: boolean;
  supports_reasoning: boolean;
  max_tokens: number;
  enabled: boolean;
}

interface CredentialEntry {
  service: string;
  has_credential: boolean;
  preview: string | null;
}

export function AIModels() {
  const mockMode = useStore((s) => s.mockMode);
  const [providers, setProviders] = useState<ProviderEntry[]>([]);
  const [defaultProvider, setDefaultProvider] = useState("");
  const [defaultModel, setDefaultModel] = useState("");
  const [selected, setSelected] = useState<ProviderEntry | null>(null);
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [creds, setCreds] = useState<CredentialEntry[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
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
    } catch (e) {
      setError(String(e));
      setStatus("error");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function selectProvider(p: ProviderEntry) {
    setSelected(p);
    setModels([]);
    try {
      const r = await api.aiModels.list(p.name);
      setModels((r.models as ModelEntry[]) ?? []);
    } catch (e) {
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
    } catch (e) {
      setError(String(e));
    } finally {
      setSyncing(false);
    }
  }

  async function testProvider(name: string) {
    setError("");
    try {
      const r = await api.aiModels.testProvider(name);
      setSyncMessage(`${name}: ${r.message}`);
    } catch (e) {
      setError(String(e));
    }
  }

  async function syncOne(name: string) {
    setError("");
    try {
      const r = await api.aiModels.sync(name);
      setSyncMessage(`Synced ${r.synced[name] ?? 0} models from ${name}.`);
      await selectProvider(selected ?? { name } as ProviderEntry);
    } catch (e) {
      setError(String(e));
    }
  }

  async function addCredential(service: string) {
    const value = window.prompt(`Enter API key for ${service}:`, "");
    if (!value) return;
    try {
      await api.aiModels.addCredential(service, value);
      await refresh();
      if (selected) await selectProvider(selected);
    } catch (e) {
      setError(String(e));
    }
  }

  async function removeCredential(service: string) {
    if (!window.confirm(`Remove credential for ${service}?`)) return;
    try {
      await api.aiModels.removeCredential(service);
      await refresh();
      if (selected) await selectProvider(selected);
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold">AI Models</h1>
          <p className="text-zinc-400 mt-1">
            Configure 52 AI providers, store API keys in the OS keyring, sync models.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={syncAll}
            disabled={syncing}
            className="bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 rounded px-3 py-1.5 text-sm"
          >
            {syncing ? "Syncing..." : "Sync All Models"}
          </button>
        </div>
      </div>

      {mockMode && (
        <div className="bg-amber-900/20 border border-amber-700 rounded-lg p-3 text-sm text-amber-300">
          Sync runs in mock mode — local providers are skipped and providers without a credential return 0.
        </div>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {syncMessage && (
        <div className="bg-zinc-800 border border-zinc-700 rounded-lg p-3 text-sm text-zinc-200">
          {syncMessage}
        </div>
      )}

      {/* Default selectors */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-zinc-500">Default Provider</label>
          <div className="mt-1 text-sm font-medium">
            {defaultProvider}{" "}
            <span className="text-xs text-zinc-500">(read-only — set via env var)</span>
          </div>
        </div>
        <div>
          <label className="text-xs text-zinc-500">Default Model</label>
          <div className="mt-1 text-sm font-medium">
            {defaultModel}{" "}
            <span className="text-xs text-zinc-500">(read-only — set via env var)</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-4">
        {/* Provider grid */}
        <div className="col-span-7">
          <div className="bg-zinc-900 border border-zinc-800 rounded-lg">
            <div className="px-4 py-3 border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500">
              Providers ({providers.length})
            </div>
            <div className="grid grid-cols-2 gap-2 p-3 max-h-[600px] overflow-y-auto">
              {status === "loading" ? (
                <div className="col-span-2 text-center py-8 text-zinc-500 text-sm">Loading...</div>
              ) : (
                providers.map((p) => (
                  <button
                    key={p.name}
                    onClick={() => selectProvider(p)}
                    className={`text-left bg-zinc-950 border rounded p-3 hover:border-zinc-600 transition-colors ${
                      selected?.name === p.name ? "border-zinc-500" : "border-zinc-800"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium truncate">{p.display_name}</span>
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded text-xs ${
                          p.has_credential
                            ? "bg-emerald-500/20 text-emerald-300"
                            : "bg-red-500/20 text-red-300"
                        }`}
                      >
                        {p.has_credential ? "Key" : "No key"}
                      </span>
                    </div>
                    <div className="text-xs text-zinc-500 mt-1 font-mono truncate">{p.name}</div>
                    {p.openai_compatible && (
                      <span className="inline-block mt-1 text-xs text-blue-300 bg-blue-500/10 border border-blue-700 rounded px-1.5 py-0.5">
                        OpenAI-compat
                      </span>
                    )}
                  </button>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Provider detail */}
        <div className="col-span-5">
          {selected ? (
            <ProviderDetail
              provider={selected}
              models={models}
              creds={creds}
              onTest={() => testProvider(selected.name)}
              onSync={() => syncOne(selected.name)}
              onAddKey={() => selected.env_key && addCredential(selected.env_key)}
              onRemoveKey={() => selected.env_key && removeCredential(selected.env_key)}
            />
          ) : (
            <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-8 text-center text-zinc-500 text-sm">
              Select a provider to view details.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ProviderDetail({
  provider,
  models,
  creds,
  onTest,
  onSync,
  onAddKey,
  onRemoveKey,
}: {
  provider: ProviderEntry;
  models: ModelEntry[];
  creds: CredentialEntry[];
  onTest: () => void;
  onSync: () => void;
  onAddKey: () => void;
  onRemoveKey: () => void;
}) {
  const cred = creds.find((c) => c.service === provider.env_key);
  const hasKey = !!cred?.has_credential;

  return (
    <div className="space-y-3">
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="text-sm font-medium">{provider.display_name}</div>
            <div className="text-xs text-zinc-500 font-mono">{provider.name}</div>
          </div>
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded text-xs ${
              hasKey
                ? "bg-emerald-500/20 text-emerald-300"
                : "bg-red-500/20 text-red-300"
            }`}
          >
            {hasKey ? "Has credential" : "No credential"}
          </span>
        </div>
        <div className="space-y-2 text-xs">
          {provider.base_url && (
            <div>
              <span className="text-zinc-500">Base URL: </span>
              <span className="font-mono text-zinc-300 break-all">{provider.base_url}</span>
            </div>
          )}
          {provider.env_key && (
            <div>
              <span className="text-zinc-500">Env key: </span>
              <span className="font-mono text-zinc-300">{provider.env_key}</span>
            </div>
          )}
          <div>
            <span className="text-zinc-500">Default model: </span>
            <span className="font-mono text-zinc-300">{provider.default_model}</span>
          </div>
          {provider.notes && (
            <div className="text-zinc-400 italic pt-1">{provider.notes}</div>
          )}
        </div>
        <div className="mt-3 flex gap-2 flex-wrap">
          <button
            onClick={onTest}
            className="bg-zinc-700 hover:bg-zinc-600 rounded px-3 py-1.5 text-xs"
          >
            Test Connection
          </button>
          <button
            onClick={onSync}
            className="bg-zinc-700 hover:bg-zinc-600 rounded px-3 py-1.5 text-xs"
          >
            Sync Models
          </button>
          {provider.env_key && !hasKey && (
            <button
              onClick={onAddKey}
              className="bg-emerald-700 hover:bg-emerald-600 rounded px-3 py-1.5 text-xs"
            >
              Add API Key
            </button>
          )}
          {provider.env_key && hasKey && (
            <button
              onClick={onRemoveKey}
              className="bg-red-900/40 hover:bg-red-800 text-red-200 rounded px-3 py-1.5 text-xs"
            >
              Remove API Key
            </button>
          )}
        </div>
      </div>

      {/* Models list */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg">
        <div className="px-4 py-2 border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500">
          Models ({models.length})
        </div>
        <div className="divide-y divide-zinc-800 max-h-96 overflow-y-auto">
          {models.length === 0 ? (
            <div className="px-4 py-8 text-center text-zinc-500 text-sm">
              No models synced. Click "Sync Models" to fetch.
            </div>
          ) : (
            models.map((m) => (
              <div key={m.id} className="px-4 py-2 flex items-center justify-between">
                <div>
                  <div className="text-sm font-mono">{m.model_id}</div>
                  <div className="text-xs text-zinc-500 mt-0.5">{m.display_name}</div>
                </div>
                <div className="flex gap-2">
                  {m.supports_vision && (
                    <span className="text-xs text-purple-300 bg-purple-500/10 border border-purple-700 rounded px-1.5 py-0.5">
                      vision
                    </span>
                  )}
                  {m.supports_reasoning && (
                    <span className="text-xs text-blue-300 bg-blue-500/10 border border-blue-700 rounded px-1.5 py-0.5">
                      reasoning
                    </span>
                  )}
                  <span className="text-xs text-zinc-500">
                    {m.max_tokens.toLocaleString()} tok
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
