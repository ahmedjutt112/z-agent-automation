/**
 * Integrations page — master prompt §54.
 * Lists OAuth providers (Google / GitHub / Facebook) with Connect buttons,
 * plus the messaging integrations (Email / WhatsApp / Telegram / Discord)
 * with a status badge and a send-message form for each.
 */

import React, { useEffect, useState } from "react";
import { api } from "../lib/api";

interface OAuthProvider {
  provider: string;
  configured: boolean;
  connected: boolean;
}

interface IntegrationEntry {
  name: string;
  category: string;
  configured: boolean;
  status: string;
}

type Status = "loading" | "ready" | "error";

export function Integrations() {
  const [oauth, setOauth] = useState<OAuthProvider[]>([]);
  const [integrations, setIntegrations] = useState<IntegrationEntry[]>([]);
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState<string>("");

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
    } catch (e) {
      setError(String(e));
      setStatus("error");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleConnect(provider: string) {
    try {
      const { authorization_url } = await api.oauth.start(provider);
      window.open(authorization_url, "_blank", "noopener,noreferrer");
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDisconnect(provider: string) {
    try {
      await api.oauth.disconnect(provider);
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  }

  const findIntegration = (name: string) =>
    integrations.find((i) => i.name === name);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Integrations</h1>
        <p className="text-zinc-400 mt-1">
          Connect OAuth providers and configure messaging channels.
        </p>
      </div>

      {status === "error" && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* OAuth section */}
      <Section title="OAuth Providers">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {oauth.map((p) => (
            <OAuthCard
              key={p.provider}
              provider={p}
              onConnect={() => handleConnect(p.provider)}
              onDisconnect={() => handleDisconnect(p.provider)}
            />
          ))}
          {oauth.length === 0 && status === "ready" && (
            <div className="text-zinc-500 text-sm col-span-3">
              No OAuth providers configured.
            </div>
          )}
        </div>
      </Section>

      {/* Email section */}
      <Section title="Email (SMTP / IMAP)">
        <IntegrationCard entry={findIntegration("email")} />
        <EmailForm onSent={refresh} />
      </Section>

      {/* WhatsApp section */}
      <Section title="WhatsApp (Business API)">
        <IntegrationCard entry={findIntegration("whatsapp")} />
        <WhatsAppForm />
      </Section>

      {/* Telegram section */}
      <Section title="Telegram (Bot API)">
        <IntegrationCard entry={findIntegration("telegram")} />
        <TelegramForm />
      </Section>

      {/* Discord section */}
      <Section title="Discord (Bot API)">
        <IntegrationCard entry={findIntegration("discord")} />
        <DiscordForm />
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-zinc-900 rounded-lg border border-zinc-800 p-4">
      <h2 className="text-sm uppercase tracking-wider text-zinc-500 mb-3">{title}</h2>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function StatusBadge({ configured, connected }: { configured: boolean; connected?: boolean }) {
  const isOk = connected ?? configured;
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
        isOk
          ? "bg-emerald-500/20 text-emerald-300 border border-emerald-700"
          : "bg-red-500/20 text-red-300 border border-red-700"
      }`}
    >
      {isOk ? (connected ? "Connected" : "Configured") : "Not configured"}
    </span>
  );
}

function OAuthCard({
  provider,
  onConnect,
  onDisconnect,
}: {
  provider: OAuthProvider;
  onConnect: () => void;
  onDisconnect: () => void;
}) {
  const label = provider.provider[0].toUpperCase() + provider.provider.slice(1);
  return (
    <div className="bg-zinc-950 border border-zinc-800 rounded-lg p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="font-medium">{label}</div>
        <StatusBadge configured={provider.configured} connected={provider.connected} />
      </div>
      <div className="flex gap-2">
        <button
          onClick={onConnect}
          disabled={!provider.configured}
          className="flex-1 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed rounded px-3 py-1.5 text-sm"
        >
          {provider.connected ? "Reconnect" : "Connect"}
        </button>
        {provider.connected && (
          <button
            onClick={onDisconnect}
            className="bg-red-900/40 hover:bg-red-800 text-red-200 rounded px-3 py-1.5 text-sm"
          >
            Disconnect
          </button>
        )}
      </div>
      {!provider.configured && (
        <div className="text-xs text-zinc-500">
          Set the {provider.provider.toUpperCase()}_OAUTH_CLIENT_ID env vars to enable.
        </div>
      )}
    </div>
  );
}

function IntegrationCard({ entry }: { entry?: IntegrationEntry }) {
  if (!entry) {
    return (
      <div className="text-sm text-zinc-500">
        Loading status…
      </div>
    );
  }
  return (
    <div className="flex items-center justify-between text-sm">
      <div className="flex items-center gap-2">
        <span className="capitalize">{entry.name}</span>
        <StatusBadge configured={entry.configured} />
      </div>
      <span className="text-xs text-zinc-500">{entry.status}</span>
    </div>
  );
}

function EmailForm({ onSent }: { onSent?: () => void }) {
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string>("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg("");
    try {
      const res = await api.integrations.sendEmail(to, subject, body);
      setMsg(
        res.sent
          ? `Sent to ${res.to.join(", ")}${res.mock ? " (mock)" : ""}`
          : "Failed to send"
      );
      setTo("");
      setSubject("");
      setBody("");
      onSent?.();
    } catch (e) {
      setMsg(`Error: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-2">
      <input
        className="bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm"
        placeholder="to@example.com"
        value={to}
        onChange={(e) => setTo(e.target.value)}
        required
      />
      <input
        className="bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm"
        placeholder="Subject"
        value={subject}
        onChange={(e) => setSubject(e.target.value)}
        required
      />
      <textarea
        className="bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm min-h-[80px]"
        placeholder="Body"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        required
      />
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={busy}
          className="bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-4 py-1.5 text-sm"
        >
          {busy ? "Sending…" : "Send Email"}
        </button>
        {msg && <span className="text-xs text-zinc-400">{msg}</span>}
      </div>
    </form>
  );
}

function WhatsAppForm() {
  const [to, setTo] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg("");
    try {
      const res = await api.integrations.sendWhatsApp(to, message);
      setMsg(`Sent (id=${res.message_id}${res.mock ? ", mock" : ""})`);
      setTo("");
      setMessage("");
    } catch (e) {
      setMsg(`Error: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-2">
      <input
        className="bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm"
        placeholder="15551234567 (international, no +)"
        value={to}
        onChange={(e) => setTo(e.target.value)}
        required
      />
      <textarea
        className="bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm min-h-[60px]"
        placeholder="Message body"
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        required
      />
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={busy}
          className="bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-4 py-1.5 text-sm"
        >
          {busy ? "Sending…" : "Send WhatsApp"}
        </button>
        {msg && <span className="text-xs text-zinc-400">{msg}</span>}
      </div>
    </form>
  );
}

function TelegramForm() {
  const [chatId, setChatId] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg("");
    try {
      const res = await api.integrations.sendTelegram(chatId, text);
      setMsg(`Sent (id=${res.message_id}${res.mock ? ", mock" : ""})`);
      setChatId("");
      setText("");
    } catch (e) {
      setMsg(`Error: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-2">
      <input
        className="bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm"
        placeholder="Chat ID or @channelname"
        value={chatId}
        onChange={(e) => setChatId(e.target.value)}
        required
      />
      <textarea
        className="bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm min-h-[60px]"
        placeholder="Text (HTML parse mode by default)"
        value={text}
        onChange={(e) => setText(e.target.value)}
        required
      />
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={busy}
          className="bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-4 py-1.5 text-sm"
        >
          {busy ? "Sending…" : "Send Telegram"}
        </button>
        {msg && <span className="text-xs text-zinc-400">{msg}</span>}
      </div>
    </form>
  );
}

function DiscordForm() {
  const [channelId, setChannelId] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg("");
    try {
      const res = await api.integrations.sendDiscord(channelId, content);
      setMsg(`Sent (id=${res.message_id}${res.mock ? ", mock" : ""})`);
      setChannelId("");
      setContent("");
    } catch (e) {
      setMsg(`Error: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-2">
      <input
        className="bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm"
        placeholder="Channel ID"
        value={channelId}
        onChange={(e) => setChannelId(e.target.value)}
        required
      />
      <textarea
        className="bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm min-h-[60px]"
        placeholder="Message content"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        required
      />
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={busy}
          className="bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-4 py-1.5 text-sm"
        >
          {busy ? "Sending…" : "Send Discord"}
        </button>
        {msg && <span className="text-xs text-zinc-400">{msg}</span>}
      </div>
    </form>
  );
}
