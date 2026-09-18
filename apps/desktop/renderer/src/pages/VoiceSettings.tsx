/** VoiceSettings page — master prompt section 46, section 72 (settings).
 *
 * Full voice configuration surface:
 *  - Wake word input (default "computer")
 *  - Voice dropdown (default / male / female + named SDK voices)
 *  - Auto-listen (continuous mode) toggle
 *  - Test button — speaks "Hello, voice control is working"
 *  - Mock mode indicator
 *  - Permission notice (section 46 invariant)
 */

import { useEffect, useState } from "react";
import { Mic, Volume2, Loader2, ShieldAlert, CheckCircle2, Radio } from "lucide-react";
import { api } from "../lib/api";

export function VoiceSettings() {
  const [wakeWord, setWakeWord] = useState("computer");
  const [voice, setVoice] = useState("default");
  const [autoListen, setAutoListen] = useState(false);
  const [mockMode, setMockMode] = useState(true);
  const [listening, setListening] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<null | "ok" | "err">(null);
  const [autoListenBusy, setAutoListenBusy] = useState(false);

  // Load current status on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await api.voice.status();
        if (cancelled) return;
        setMockMode(s.mock_mode);
        setListening(s.listening);
        if (s.wake_word) setWakeWord(s.wake_word);
        setAutoListen(s.listening);
      } catch {
        // ignore — service may be down during development
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      await api.voice.speak("Hello, voice control is working", voice);
      setTestResult("ok");
    } catch {
      setTestResult("err");
    } finally {
      setTesting(false);
    }
  }

  async function toggleAutoListen() {
    setAutoListenBusy(true);
    try {
      if (autoListen) {
        await api.voice.stopContinuous();
        setAutoListen(false);
        setListening(false);
      } else {
        await api.voice.startContinuous();
        setAutoListen(true);
        setListening(true);
      }
    } catch {
      // ignore for now — surfaced via status polling
    } finally {
      setAutoListenBusy(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <Mic size={22} className="text-blue-400" />
          Voice Settings
        </h1>
        {mockMode && (
          <span className="text-xs px-2 py-1 rounded bg-amber-950/60 border border-amber-700 text-amber-300">
            Mock mode active — no real audio captured
          </span>
        )}
      </div>

      {/* Security notice — section 46 */}
      <div className="mb-6 flex items-start gap-2 text-sm text-amber-200 bg-amber-950/30 border border-amber-800 rounded-lg px-4 py-3">
        <ShieldAlert size={16} className="mt-0.5 flex-shrink-0" />
        <div>
          <strong>Permission required.</strong> Voice commands never bypass the
          security confirmation flow. Even in continuous mode, every plan
          requires explicit user approval before execution.
        </div>
      </div>

      <div className="space-y-4 max-w-2xl">
        {/* Wake word */}
        <SettingRow
          label="Wake word"
          hint="Say this word before issuing a command in continuous mode"
        >
          <input
            type="text"
            value={wakeWord}
            onChange={(e) => setWakeWord(e.target.value)}
            placeholder="computer"
            className="bg-zinc-950 border border-zinc-700 rounded px-3 py-2 text-sm text-zinc-100 w-full focus:outline-none focus:border-blue-500"
          />
        </SettingRow>

        {/* Voice selection */}
        <SettingRow
          label="Voice"
          hint="Voice used for text-to-speech output"
        >
          <select
            value={voice}
            onChange={(e) => setVoice(e.target.value)}
            className="bg-zinc-950 border border-zinc-700 rounded px-3 py-2 text-sm text-zinc-100 w-full focus:outline-none focus:border-blue-500"
          >
            <option value="default">Default (warm, friendly — tongtong)</option>
            <option value="male">Male (calm, professional — xiaochen)</option>
            <option value="female">Female (warm, friendly — tongtong)</option>
            <option value="tongtong">tongtong (named)</option>
            <option value="chuichui">chuichui (named)</option>
            <option value="xiaochen">xiaochen (named)</option>
            <option value="jam">jam (named)</option>
            <option value="kazi">kazi (named)</option>
            <option value="douji">douji (named)</option>
            <option value="luodo">luodo (named)</option>
          </select>
        </SettingRow>

        {/* Continuous listening toggle */}
        <SettingRow
          label="Auto-listen (continuous mode)"
          hint="Listen for the wake word in the background"
        >
          <div className="flex items-center gap-3">
            <button
              onClick={toggleAutoListen}
              disabled={autoListenBusy}
              className={`relative w-12 h-6 rounded-full transition-colors ${
                autoListen ? "bg-blue-600" : "bg-zinc-700"
              } ${autoListenBusy ? "opacity-50" : ""}`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
                  autoListen ? "translate-x-6" : ""
                }`}
              />
            </button>
            <span className="text-xs text-zinc-400">
              {listening ? (
                <span className="flex items-center gap-1 text-green-400">
                  <Radio size={12} className="animate-pulse" />
                  Listening for wake word "{wakeWord}"
                </span>
              ) : (
                "Off"
              )}
            </span>
          </div>
        </SettingRow>

        {/* Test button */}
        <SettingRow
          label="Test voice output"
          hint='Speaks "Hello, voice control is working" using the selected voice'
        >
          <div className="flex items-center gap-3">
            <button
              onClick={handleTest}
              disabled={testing}
              className="px-4 py-2 text-sm rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-100 flex items-center gap-2 disabled:opacity-50"
            >
              {testing ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Volume2 size={14} />
              )}
              {testing ? "Speaking..." : "Test voice"}
            </button>
            {testResult === "ok" && (
              <span className="text-xs text-green-400 flex items-center gap-1">
                <CheckCircle2 size={12} />
                Spoken successfully
              </span>
            )}
            {testResult === "err" && (
              <span className="text-xs text-red-400">
                Test failed — check service is running
              </span>
            )}
          </div>
        </SettingRow>

        {/* Mock mode indicator */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <div className="text-sm font-medium mb-1 flex items-center gap-2">
            <Radio size={14} className="text-amber-400" />
            Mode
          </div>
          <div className="text-xs text-zinc-400">
            {mockMode ? (
              <>
                <strong className="text-amber-300">Mock mode</strong> — voice
                capture and synthesis return deterministic test data without
                touching audio hardware. Disable mock mode in
                <code className="text-zinc-300 mx-1 bg-zinc-950 px-1 rounded">.env</code>
                (<code className="text-zinc-300 bg-zinc-950 px-1 rounded">AUTOMATION_MOCK_MODE=false</code>)
                to use the real microphone + Z.ai ASR / TTS APIs.
              </>
            ) : (
              <>
                <strong className="text-green-300">Live mode</strong> — the
                microphone and speaker will be used for STT and TTS. Requires
                the <code className="text-zinc-300 bg-zinc-950 px-1 rounded">z-ai</code>
                CLI (<code className="text-zinc-300 bg-zinc-950 px-1 rounded">npm install -g z-ai-web-dev-sdk</code>)
                and <code className="text-zinc-300 bg-zinc-950 px-1 rounded">sounddevice</code>
                + <code className="text-zinc-300 bg-zinc-950 px-1 rounded">soundfile</code>
                Python packages.
              </>
            )}
          </div>
        </div>

        {/* Permission notice (section 46) */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <div className="text-sm font-medium mb-2">Permission flow</div>
          <ol className="text-xs text-zinc-400 space-y-1 list-decimal list-inside">
            <li>You speak a command (e.g. "open chrome and search for AI")</li>
            <li>Speech-to-text transcribes the audio</li>
            <li>AI planner generates a structured plan with risk levels</li>
            <li>Plan is displayed for explicit review</li>
            <li>
              <strong className="text-zinc-200">You click "Approve &amp; Run"</strong>
              {" "}— even for low-risk plans, voice never bypasses this step
            </li>
            <li>Permission engine re-evaluates the plan (defense in depth)</li>
            <li>Automation engine executes step-by-step</li>
          </ol>
        </div>
      </div>
    </div>
  );
}

function SettingRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
      <div className="flex items-start justify-between gap-4 mb-2">
        <div>
          <div className="text-sm font-medium">{label}</div>
          {hint && <div className="text-xs text-zinc-500 mt-0.5">{hint}</div>}
        </div>
      </div>
      {children}
    </div>
  );
}
