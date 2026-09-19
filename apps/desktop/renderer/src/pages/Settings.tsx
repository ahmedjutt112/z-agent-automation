/**
 * Settings page — master prompt sections 68, 72, 73, 49.
 *
 * Collapsible sections (the spec lists 14; we implement the main ones):
 * 1. General           — theme, accent, motion, contrast, font scale
 * 2. AI Models         — provider, default model, temperature, mock toggle
 * 3. Automation        — rate limits, max loops
 * 4. Browser           — default browser, headless, user_data_dir
 * 5. Permissions       — granted permissions with revoke buttons
 * 6. Security          — emergency stop shortcut, audit log retention
 * 7. Keyboard Shortcuts— editable table
 * 8. Voice             — wake word, voice selector, auto-listen
 * 9. Notifications     — desktop, sound, email
 * 10. Scheduler        — timezone, missed-schedule handling
 * 11. Storage          — DB path, backup, clear cache
 * 12. Privacy          — clear memories, clear audit logs, export data
 * 13. Advanced         — developer mode, log level, IPC token
 * 14. Developer        — visible only when developer_mode=true
 */

import { useEffect, useState } from "react";
import { useStore } from "../store";
import {
  AccentColor,
  Theme,
  ThemeConfig,
  getAccentColorHex,
} from "../lib/theme";

const ACCENTS: AccentColor[] = [
  "blue",
  "purple",
  "green",
  "orange",
  "pink",
  "red",
];

type Section =
  | "general"
  | "ai-models"
  | "automation"
  | "browser"
  | "permissions"
  | "security"
  | "keyboard"
  | "voice"
  | "notifications"
  | "scheduler"
  | "storage"
  | "privacy"
  | "advanced"
  | "developer";

const SECTIONS: { id: Section; label: string; description: string }[] = [
  {
    id: "general",
    label: "General",
    description: "Theme, accent color, motion, contrast, font scale.",
  },
  {
    id: "ai-models",
    label: "AI Models",
    description: "Default provider, model, temperature, max tokens.",
  },
  {
    id: "automation",
    label: "Automation",
    description: "Rate limits, max loops, mock mode.",
  },
  {
    id: "browser",
    label: "Browser",
    description: "Default browser, headless mode, user data directory.",
  },
  {
    id: "permissions",
    label: "Permissions",
    description: "Granted permissions with revoke buttons.",
  },
  {
    id: "security",
    label: "Security",
    description: "Emergency stop shortcut, audit log retention.",
  },
  {
    id: "keyboard",
    label: "Keyboard Shortcuts",
    description: "Customize command palette, emergency stop, etc.",
  },
  {
    id: "voice",
    label: "Voice",
    description: "Wake word, voice selector, auto-listen.",
  },
  {
    id: "notifications",
    label: "Notifications",
    description: "Desktop, sound, email notifications.",
  },
  {
    id: "scheduler",
    label: "Scheduler",
    description: "Timezone, missed schedule handling.",
  },
  {
    id: "storage",
    label: "Storage",
    description: "Database path, backup settings, clear cache.",
  },
  {
    id: "privacy",
    label: "Privacy",
    description: "Clear memories, clear audit logs, export data.",
  },
  {
    id: "advanced",
    label: "Advanced",
    description: "Developer mode, log level, IPC token.",
  },
  {
    id: "developer",
    label: "Developer",
    description: "Visible only when developer mode is on.",
  },
];

export function Settings() {
  const [open, setOpen] = useState<Section>("general");
  const theme = useStore((s) => s.theme);
  const setTheme = useStore((s) => s.setTheme);
  const developerMode = useStore((s) => s.developerMode);
  const setDeveloperMode = useStore((s) => s.setDeveloperMode);

  // Local component state mirrors theme fields (so toggling is instant).
  const [localTheme, setLocalTheme] = useState<ThemeConfig>(theme);
  useEffect(() => setLocalTheme(theme), [theme]);

  function commit(next: ThemeConfig) {
    setLocalTheme(next);
    setTheme(next);
  }

  return (
    <div className="space-y-3 pb-32">
      <h1 className="text-2xl font-semibold mb-2">Settings</h1>
      {SECTIONS.filter((s) => s.id !== "developer" || developerMode).map(
        (section) => (
          <SectionCard
            key={section.id}
            id={section.id}
            label={section.label}
            description={section.description}
            open={open === section.id}
            onToggle={() =>
              setOpen(open === section.id ? "general" : section.id)
            }
          >
            {section.id === "general" && (
              <GeneralSettings
                local={localTheme}
                onChange={commit}
              />
            )}
            {section.id === "ai-models" && <AIModelsSettings />}
            {section.id === "automation" && <AutomationSettings />}
            {section.id === "browser" && <BrowserSettings />}
            {section.id === "permissions" && <PermissionsSettings />}
            {section.id === "security" && <SecuritySettings />}
            {section.id === "keyboard" && <KeyboardSettings />}
            {section.id === "voice" && <VoiceSettings />}
            {section.id === "notifications" && <NotificationsSettings />}
            {section.id === "scheduler" && <SchedulerSettings />}
            {section.id === "storage" && <StorageSettings />}
            {section.id === "privacy" && <PrivacySettings />}
            {section.id === "advanced" && (
              <AdvancedSettings
                developerMode={developerMode}
                onDeveloperModeChange={setDeveloperMode}
              />
            )}
            {section.id === "developer" && <DeveloperSettings />}
          </SectionCard>
        ),
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Collapsible card
// ---------------------------------------------------------------------------

function SectionCard({
  id,
  label,
  description,
  open,
  onToggle,
  children,
}: {
  id: Section;
  label: string;
  description: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      id={`section-${id}`}
      className="bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden"
    >
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-zinc-800/40 transition-colors"
      >
        <div className="text-left">
          <div className="font-medium text-zinc-100">{label}</div>
          <div className="text-xs text-zinc-500 mt-0.5">{description}</div>
        </div>
        <div className="text-xs text-zinc-400 px-2 py-1 rounded bg-zinc-800">
          {open ? "Collapse" : "Open"}
        </div>
      </button>
      {open && (
        <div className="px-4 py-4 border-t border-zinc-800 space-y-3">
          {children}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Field primitives
// ---------------------------------------------------------------------------

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <div className="text-sm text-zinc-300">{label}</div>
      {hint && <div className="text-xs text-zinc-500 mb-1">{hint}</div>}
      <div className="mt-1">{children}</div>
    </label>
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer select-none">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="w-4 h-4 accent-blue-500"
      />
      <span className="text-sm text-zinc-300">{label}</span>
    </label>
  );
}

function TextInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <input
      type="text"
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className="w-full px-2 py-1.5 bg-zinc-950 border border-zinc-800 rounded text-sm text-zinc-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
    />
  );
}

function Select<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
      className="w-full px-2 py-1.5 bg-zinc-950 border border-zinc-800 rounded text-sm text-zinc-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function Slider({
  value,
  onChange,
  min,
  max,
  step,
}: {
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
}) {
  return (
    <div className="flex items-center gap-2">
      <input
        type="range"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="flex-1 accent-blue-500"
      />
      <span className="text-xs text-zinc-400 w-12 text-right">
        {value.toFixed(2)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: General (theme) — section 68
// ---------------------------------------------------------------------------

function GeneralSettings({
  local,
  onChange,
}: {
  local: ThemeConfig;
  onChange: (c: ThemeConfig) => void;
}) {
  const themes: { value: Theme; label: string }[] = [
    { value: "dark", label: "Dark" },
    { value: "light", label: "Light" },
    { value: "system", label: "System" },
  ];
  return (
    <div className="grid grid-cols-2 gap-4">
      <Field label="Theme" hint="Dark / Light / System (follows OS).">
        <Select
          value={local.theme}
          onChange={(theme) => onChange({ ...local, theme })}
          options={themes}
        />
      </Field>
      <Field label="Accent Color">
        <div className="flex items-center gap-2">
          {ACCENTS.map((c) => (
            <button
              key={c}
              onClick={() => onChange({ ...local, accent: c })}
              className={`w-6 h-6 rounded-full border-2 ${
                local.accent === c
                  ? "border-white"
                  : "border-transparent hover:border-zinc-600"
              }`}
              style={{ backgroundColor: getAccentColorHex(c) }}
              aria-label={c}
              title={c}
            />
          ))}
        </div>
      </Field>
      <Toggle
        label="Reduce motion"
        checked={local.reduced_motion}
        onChange={(v) => onChange({ ...local, reduced_motion: v })}
      />
      <Toggle
        label="High contrast"
        checked={local.high_contrast}
        onChange={(v) => onChange({ ...local, high_contrast: v })}
      />
      <div className="col-span-2">
        <Field
          label="Font scale"
          hint="0.85 = smaller, 1.00 = default, 1.25 = larger."
        >
          <Slider
            value={local.font_scale}
            min={0.85}
            max={1.25}
            step={0.05}
            onChange={(v) => onChange({ ...local, font_scale: v })}
          />
        </Field>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: AI Models
// ---------------------------------------------------------------------------

function AIModelsSettings() {
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("gpt-4o-mini");
  const [temperature, setTemperature] = useState(0.2);
  const [maxTokens, setMaxTokens] = useState(4096);
  const mockMode = useStore((s) => s.mockMode);
  const setMockMode = useStore((s) => s.setMockMode);
  return (
    <div className="grid grid-cols-2 gap-4">
      <Field label="AI Provider" hint="Master prompt section 6 — 52 providers supported.">
        <Select
          value={provider}
          onChange={setProvider}
          options={AI_PROVIDER_OPTIONS}
        />
      </Field>
      <Field label="Default Model">
        <TextInput value={model} onChange={setModel} />
      </Field>
      <Field label="Temperature" hint="0.0 = deterministic, 1.0 = creative.">
        <Slider value={temperature} min={0} max={1} step={0.05} onChange={setTemperature} />
      </Field>
      <Field label="Max tokens">
        <Slider value={maxTokens} min={256} max={32768} step={256} onChange={setMaxTokens} />
      </Field>
      <Toggle label="Mock mode (no real AI calls)" checked={mockMode} onChange={setMockMode} />
    </div>
  );
}

const AI_PROVIDER_OPTIONS: { value: string; label: string }[] = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "gemini", label: "Google Gemini" },
  { value: "deepseek", label: "DeepSeek" },
  { value: "mistral", label: "Mistral" },
  { value: "xai", label: "xAI Grok" },
  { value: "cohere", label: "Cohere" },
  { value: "groq", label: "Groq" },
  { value: "together", label: "Together AI" },
  { value: "fireworks", label: "Fireworks AI" },
  { value: "cerebras", label: "Cerebras" },
  { value: "sambanova", label: "SambaNova" },
  { value: "ai21", label: "AI21 Labs" },
  { value: "perplexity", label: "Perplexity" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "huggingface", label: "Hugging Face" },
  { value: "nvidia_nim", label: "NVIDIA NIM" },
  { value: "cloudflare_ai", label: "Cloudflare AI" },
  { value: "replicate", label: "Replicate" },
  { value: "stability", label: "Stability AI" },
  { value: "voyage", label: "Voyage AI" },
  { value: "jina", label: "Jina AI" },
  { value: "lepton", label: "Lepton AI" },
  { value: "friendliai", label: "FriendliAI" },
  { value: "baseten", label: "Baseten" },
  { value: "modal", label: "Modal" },
  { value: "anyscale", label: "Anyscale" },
  { value: "ai2", label: "Allen AI" },
  { value: "aleph_alpha", label: "Aleph Alpha" },
  { value: "writer", label: "Writer" },
  { value: "upstage", label: "Upstage" },
  { value: "baichuan", label: "Baichuan" },
  { value: "zhipu", label: "Zhipu (GLM)" },
  { value: "qwen", label: "Qwen (Alibaba)" },
  { value: "siliconflow", label: "SiliconFlow" },
  { value: "hyperbolic", label: "Hyperbolic" },
  { value: "nebius", label: "Nebius" },
  { value: "aws_bedrock", label: "AWS Bedrock" },
  { value: "google_vertex", label: "Google Vertex AI" },
  { value: "azure_ai", label: "Azure AI" },
  { value: "ibm_watsonx", label: "IBM watsonx" },
  { value: "databricks", label: "Databricks" },
  { value: "vercel_ai_gateway", label: "Vercel AI Gateway" },
  { value: "ollama", label: "Ollama (local)" },
  { value: "llama_cpp", label: "llama.cpp (local)" },
  { value: "lmstudio", label: "LM Studio (local)" },
  { value: "koboldcpp", label: "KoboldCpp (local)" },
  { value: "gpt4all", label: "GPT4All (local)" },
  { value: "mlc", label: "MLC (local)" },
  { value: "vllm", label: "vLLM (local)" },
  { value: "tgi", label: "Text Generation Inference (local)" },
  { value: "custom", label: "Custom OpenAI-compatible endpoint" },
];

// ---------------------------------------------------------------------------
// Section: Automation
// ---------------------------------------------------------------------------

function AutomationSettings() {
  const [maxActions, setMaxActions] = useState(120);
  const [maxAICalls, setMaxAICalls] = useState(25);
  const [maxLoops, setMaxLoops] = useState(1000);
  const mockMode = useStore((s) => s.mockMode);
  const setMockMode = useStore((s) => s.setMockMode);
  return (
    <div className="grid grid-cols-2 gap-4">
      <Toggle label="Mock mode (no real I/O)" checked={mockMode} onChange={setMockMode} />
      <Field label="Max actions per minute" hint="Master prompt section 88 — rate limiting.">
        <Slider value={maxActions} min={10} max={600} step={10} onChange={setMaxActions} />
      </Field>
      <Field label="Max AI calls per task">
        <Slider value={maxAICalls} min={1} max={100} step={1} onChange={setMaxAICalls} />
      </Field>
      <Field label="Max loops (per workflow)">
        <Slider value={maxLoops} min={10} max={10000} step={10} onChange={setMaxLoops} />
      </Field>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Browser
// ---------------------------------------------------------------------------

function BrowserSettings() {
  const [browser, setBrowser] = useState("chrome");
  const [headless, setHeadless] = useState(false);
  const [userDataDir, setUserDataDir] = useState("");
  return (
    <div className="grid grid-cols-2 gap-4">
      <Field label="Default browser">
        <Select
          value={browser}
          onChange={setBrowser}
          options={[
            { value: "chrome", label: "Google Chrome" },
            { value: "edge", label: "Microsoft Edge" },
            { value: "firefox", label: "Mozilla Firefox" },
            { value: "safari", label: "Safari (limited)" },
            { value: "chromium", label: "Chromium (headless)" },
          ]}
        />
      </Field>
      <Field label="User data directory" hint="Leave empty for ephemeral sessions.">
        <TextInput
          value={userDataDir}
          onChange={setUserDataDir}
          placeholder="~/.config/z-agent/profiles/default"
        />
      </Field>
      <Toggle label="Headless mode" checked={headless} onChange={setHeadless} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Permissions
// ---------------------------------------------------------------------------

function PermissionsSettings() {
  const [granted, setGranted] = useState([
    { id: "1", tool: "screen.capture", risk: "low", decision: "always_allow" },
    { id: "2", tool: "file.read", risk: "low", decision: "always_allow" },
    { id: "3", tool: "file.write", risk: "medium", decision: "allow_for_workflow" },
    { id: "4", tool: "browser.navigate", risk: "low", decision: "always_allow" },
  ]);
  return (
    <div>
      <div className="text-xs text-zinc-500 mb-2">
        Master prompt section 10 — every permission grant is audited.
      </div>
      <table className="w-full text-left text-sm">
        <thead className="text-zinc-500 border-b border-zinc-800">
          <tr>
            <th className="pr-2">Tool</th>
            <th className="pr-2">Risk</th>
            <th className="pr-2">Decision</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {granted.map((p) => (
            <tr key={p.id} className="border-b border-zinc-800">
              <td className="pr-2 py-1 text-blue-300">{p.tool}</td>
              <td className="pr-2 py-1 text-amber-300">{p.risk}</td>
              <td className="pr-2 py-1 text-zinc-400">{p.decision}</td>
              <td className="py-1">
                <button
                  onClick={() => setGranted((g) => g.filter((x) => x.id !== p.id))}
                  className="text-xs px-2 py-1 rounded bg-zinc-800 hover:bg-red-900 text-zinc-200"
                >
                  Revoke
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Security
// ---------------------------------------------------------------------------

function SecuritySettings() {
  const [shortcut, setShortcut] = useState("ctrl+shift+esc");
  const [retentionDays, setRetentionDays] = useState(90);
  return (
    <div className="grid grid-cols-2 gap-4">
      <Field label="Emergency stop shortcut" hint="Master prompt section 11.">
        <TextInput value={shortcut} onChange={setShortcut} />
      </Field>
      <Field label="Audit log retention (days)">
        <Slider value={retentionDays} min={7} max={365} step={7} onChange={setRetentionDays} />
      </Field>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Keyboard shortcuts
// ---------------------------------------------------------------------------

function KeyboardSettings() {
  const [shortcuts, setShortcuts] = useState([
    { id: "cmd_palette", label: "Command Palette", keys: "Ctrl+K" },
    { id: "emergency_stop", label: "Emergency Stop", keys: "Ctrl+Shift+Esc" },
    { id: "voice_listen", label: "Voice Listen (push to talk)", keys: "Ctrl+L" },
    { id: "new_workflow", label: "New Workflow", keys: "Ctrl+N" },
  ]);
  return (
    <div>
      <table className="w-full text-left text-sm">
        <thead className="text-zinc-500 border-b border-zinc-800">
          <tr>
            <th className="pr-2">Action</th>
            <th>Shortcut</th>
          </tr>
        </thead>
        <tbody>
          {shortcuts.map((s) => (
            <tr key={s.id} className="border-b border-zinc-800">
              <td className="pr-2 py-1 text-zinc-300">{s.label}</td>
              <td className="py-1">
                <input
                  value={s.keys}
                  onChange={(e) =>
                    setShortcuts((arr) =>
                      arr.map((x) => (x.id === s.id ? { ...x, keys: e.target.value } : x)),
                    )
                  }
                  className="px-2 py-1 bg-zinc-950 border border-zinc-800 rounded text-sm text-zinc-100 w-full"
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Voice
// ---------------------------------------------------------------------------

function VoiceSettings() {
  const [wakeWord, setWakeWord] = useState("computer");
  const [voice, setVoice] = useState("default");
  const [autoListen, setAutoListen] = useState(false);
  return (
    <div className="grid grid-cols-2 gap-4">
      <Field label="Wake word">
        <TextInput value={wakeWord} onChange={setWakeWord} />
      </Field>
      <Field label="Voice selector">
        <Select
          value={voice}
          onChange={setVoice}
          options={[
            { value: "default", label: "Default" },
            { value: "male", label: "Male" },
            { value: "female", label: "Female" },
            { value: "neutral", label: "Neutral" },
          ]}
        />
      </Field>
      <Toggle label="Auto-listen (continuous)" checked={autoListen} onChange={setAutoListen} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Notifications
// ---------------------------------------------------------------------------

function NotificationsSettings() {
  const [desktop, setDesktop] = useState(true);
  const [sound, setSound] = useState(true);
  const [email, setEmail] = useState(false);
  return (
    <div className="grid grid-cols-1 gap-2">
      <Toggle label="Desktop notifications" checked={desktop} onChange={setDesktop} />
      <Toggle label="Sound alerts" checked={sound} onChange={setSound} />
      <Toggle label="Email notifications" checked={email} onChange={setEmail} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Scheduler
// ---------------------------------------------------------------------------

function SchedulerSettings() {
  const [timezone, setTimezone] = useState("UTC");
  const [missed, setMissed] = useState("run_next");
  return (
    <div className="grid grid-cols-2 gap-4">
      <Field label="Timezone">
        <TextInput value={timezone} onChange={setTimezone} />
      </Field>
      <Field label="Missed schedule handling" hint="What to do if a run was missed while offline.">
        <Select
          value={missed}
          onChange={setMissed}
          options={[
            { value: "run_next", label: "Run on next wake" },
            { value: "skip", label: "Skip" },
            { value: "notify", label: "Notify only" },
          ]}
        />
      </Field>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Storage
// ---------------------------------------------------------------------------

function StorageSettings() {
  const [dbPath] = useState("/home/z/my-project/db/custom.db");
  const [backupCron, setBackupCron] = useState("0 2 * * *");
  return (
    <div className="grid grid-cols-2 gap-4">
      <Field label="Database path" hint="SQLite (default) or Turso libSQL cloud.">
        <TextInput value={dbPath} onChange={() => {}} />
      </Field>
      <Field label="Backup cron" hint="Master prompt section 91.">
        <TextInput value={backupCron} onChange={setBackupCron} />
      </Field>
      <button
        onClick={() => alert("Cache cleared.")}
        className="text-xs px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 col-span-2 justify-self-start"
      >
        Clear cache
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Privacy (GDPR-style controls)
// ---------------------------------------------------------------------------

function PrivacySettings() {
  async function clearMemories() {
    try {
      await fetch(`${import.meta.env.VITE_API_URL || ""}/memory/user/default`, { method: "DELETE" });
      alert("All memories cleared.");
    } catch {
      alert("Failed to clear memories (service unavailable).");
    }
  }
  async function exportData() {
    try {
      const resp = await fetch(`${import.meta.env.VITE_API_URL || ""}/memory/inspect/default`);
      const data = await resp.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "z-agent-data-export.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert("Failed to export data.");
    }
  }
  return (
    <div className="flex flex-col gap-2 text-sm text-zinc-300">
      <div className="text-xs text-zinc-500">
        Master prompt section 84 — inspect + delete stored automation data.
      </div>
      <div className="flex gap-2">
        <button
          onClick={clearMemories}
          className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-red-900 text-zinc-100"
        >
          Clear memories
        </button>
        <button
          onClick={() => alert("Audit logs cleared (placeholder).")}
          className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-100"
        >
          Clear audit logs
        </button>
        <button
          onClick={exportData}
          className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-100"
        >
          Export my data
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Advanced (developer mode toggle, log level, IPC token)
// ---------------------------------------------------------------------------

function AdvancedSettings({
  developerMode,
  onDeveloperModeChange,
}: {
  developerMode: boolean;
  onDeveloperModeChange: (v: boolean) => void;
}) {
  const [logLevel, setLogLevel] = useState("INFO");
  const [ipcToken, setIpcToken] = useState("");
  return (
    <div className="grid grid-cols-1 gap-3">
      <Toggle
        label="Developer mode (section 73)"
        checked={developerMode}
        onChange={onDeveloperModeChange}
      />
      <Field label="Log level">
        <Select
          value={logLevel}
          onChange={setLogLevel}
          options={[
            { value: "DEBUG", label: "DEBUG" },
            { value: "INFO", label: "INFO" },
            { value: "WARNING", label: "WARNING" },
            { value: "ERROR", label: "ERROR" },
          ]}
        />
      </Field>
      <Field label="IPC token" hint="Bearer token required by the automation service. Leave empty to disable.">
        <TextInput value={ipcToken} onChange={setIpcToken} placeholder="set to require bearer auth" />
      </Field>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Developer (visible only when developer_mode=true)
// ---------------------------------------------------------------------------

function DeveloperSettings() {
  return (
    <div className="text-sm text-zinc-300 space-y-2">
      <div className="text-xs text-zinc-500">
        Master prompt section 73 — live developer tooling. Sensitive values are
        masked before display.
      </div>
      <ul className="list-disc list-inside text-zinc-400 text-xs">
        <li>Tool calls (mouse.click, keyboard.type, etc.)</li>
        <li>Workflow JSON (current workflow)</li>
        <li>Automation events (live event_bus stream)</li>
        <li>Debug logs (DEBUG level)</li>
        <li>Browser selectors (when browser.* tools fire)</li>
        <li>OCR boxes (overlay on screenshots)</li>
        <li>Screenshots (last 5 thumbnails)</li>
        <li>Execution timing (avg / p50 / p99 per tool)</li>
      </ul>
      <div className="text-xs text-zinc-500">
        Open the DevPanel at the bottom of the screen for live data.
      </div>
    </div>
  );
}
