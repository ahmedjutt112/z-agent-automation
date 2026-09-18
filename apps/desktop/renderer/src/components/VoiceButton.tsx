/**
 * VoiceButton — master prompt section 46 (Voice Control).
 *
 * Floating voice control button (bottom-right corner). Implements the
 * voice pipeline:
 *
 *     Microphone -> Speech-to-Text -> AI Planner -> Permission Engine
 *               -> Automation Engine
 *
 * CRITICAL INVARIANT (section 46): voice commands NEVER bypass the
 * security confirmation flow. The "Approve & Run" button is the only
 * way to execute a plan; even if the user said "delete all files",
 * the plan is still surfaced for explicit approval.
 */

import { useState } from "react";
import { Mic, MicOff, Settings as SettingsIcon, X, Loader2, ShieldAlert, Play } from "lucide-react";
import { api, Plan } from "../lib/api";
import { useStore } from "../store";

type VoicePhase = "idle" | "listening" | "planning" | "ready" | "executing" | "done" | "error";

interface PlanResult {
  transcript: string;
  plan: Plan;
}

export function VoiceButton() {
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [result, setResult] = useState<PlanResult | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const setView = useStore((s) => s.setView);

  async function handleStartListening() {
    setPhase("listening");
    setError(null);
    setResult(null);
    setRunId(null);
    try {
      // Pipeline step 1-3: STT + AI Planner. NO execution.
      setPhase("planning");
      const r = await api.voice.listenAndPlan();
      setResult({ transcript: r.transcript, plan: r.plan });
      setPhase("ready");
    } catch (e: any) {
      setError(e?.message || "Voice listen-and-plan failed");
      setPhase("error");
    }
  }

  async function handleApproveAndRun() {
    if (!result) return;
    setPhase("executing");
    setError(null);
    try {
      const r = await api.voice.listenAndExecute(result.plan);
      setRunId(r.run_id);
      setPhase("done");
    } catch (e: any) {
      setError(e?.message || "Plan execution failed");
      setPhase("error");
    }
  }

  function handleCancel() {
    setResult(null);
    setRunId(null);
    setError(null);
    setPhase("idle");
  }

  function openSettings() {
    setSettingsOpen(true);
  }

  function goToVoiceSettings() {
    setSettingsOpen(false);
    setView("voice-settings" as any);
  }

  const listening = phase === "listening" || phase === "planning";
  const busy = phase === "executing";

  return (
    <>
      {/* Floating button cluster — bottom-right corner */}
      <div className="fixed bottom-6 right-6 z-40 flex flex-col items-end gap-2">
        <button
          onClick={openSettings}
          title="Voice settings"
          className="w-9 h-9 rounded-full bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-300 flex items-center justify-center shadow-lg"
        >
          <SettingsIcon size={16} />
        </button>
        <button
          onClick={handleStartListening}
          disabled={listening || busy}
          title={listening ? "Listening..." : "Click to speak"}
          className={`w-14 h-14 rounded-full border flex items-center justify-center shadow-xl transition-all ${
            listening
              ? "bg-red-600 border-red-400 animate-pulse"
              : "bg-zinc-800 hover:bg-zinc-700 border-zinc-600 text-zinc-100"
          } ${busy ? "opacity-50 cursor-not-allowed" : ""}`}
        >
          {listening ? (
            <Mic size={22} className="text-white" />
          ) : (
            <Mic size={22} />
          )}
        </button>
        {listening && (
          <div className="text-xs text-zinc-400 bg-zinc-900/80 px-2 py-1 rounded border border-zinc-800">
            Listening...
          </div>
        )}
      </div>

      {/* Approval modal — shown when transcript + plan are ready */}
      {phase === "ready" && result && (
        <div
          className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={handleCancel}
        >
          <div
            className="w-full max-w-2xl bg-zinc-900 border border-zinc-700 rounded-lg shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <Mic size={16} className="text-blue-400" />
                <span className="text-sm font-medium text-zinc-100">
                  Voice command review
                </span>
              </div>
              <button
                onClick={handleCancel}
                className="text-zinc-400 hover:text-white"
              >
                <X size={18} />
              </button>
            </div>

            <div className="p-5 space-y-4 max-h-[70vh] overflow-y-auto">
              {/* Transcript */}
              <div>
                <div className="text-xs uppercase tracking-wider text-zinc-500 mb-1">
                  You said
                </div>
                <div className="text-sm text-zinc-100 italic bg-zinc-950/50 border border-zinc-800 rounded px-3 py-2">
                  "{result.transcript}"
                </div>
              </div>

              {/* Plan summary */}
              <div>
                <div className="text-xs uppercase tracking-wider text-zinc-500 mb-1">
                  AI plan
                </div>
                <div className="text-sm text-zinc-200 mb-2">
                  Goal: <span className="text-zinc-100">{result.plan.goal}</span>
                </div>
                <div className="flex flex-wrap gap-2 text-xs mb-3">
                  <RiskBadge level={result.plan.overall_risk} />
                  <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300">
                    {result.plan.steps.length} steps
                  </span>
                  <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300">
                    ~{result.plan.estimated_duration_seconds}s
                  </span>
                </div>

                {/* Steps list */}
                <ol className="space-y-2">
                  {result.plan.steps.map((step, i) => (
                    <li
                      key={step.id}
                      className="text-xs flex items-start gap-2 bg-zinc-950/40 border border-zinc-800 rounded px-3 py-2"
                    >
                      <span className="text-zinc-500 mt-0.5">{i + 1}.</span>
                      <div className="flex-1">
                        <div className="font-mono text-zinc-200">{step.action}</div>
                        <div className="text-zinc-500 mt-0.5">
                          args: {JSON.stringify(step.args)}
                        </div>
                      </div>
                      <RiskBadge level={step.risk_level} small />
                    </li>
                  ))}
                </ol>

                {result.plan.potential_side_effects?.length > 0 && (
                  <div className="mt-3 text-xs text-amber-300 bg-amber-950/30 border border-amber-800 rounded px-3 py-2">
                    Side effects: {result.plan.potential_side_effects.join(", ")}
                  </div>
                )}
              </div>

              {/* Security notice — section 46 */}
              <div className="flex items-start gap-2 text-xs text-amber-200 bg-amber-950/30 border border-amber-800 rounded px-3 py-2">
                <ShieldAlert size={14} className="mt-0.5 flex-shrink-0" />
                <div>
                  <strong>Security confirmation required.</strong> Voice commands
                  never bypass the permission engine. Review the plan above and
                  click "Approve & Run" to execute — or "Cancel" to discard.
                </div>
              </div>
            </div>

            {/* Action bar */}
            <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-zinc-800 bg-zinc-950/40">
              <button
                onClick={handleCancel}
                className="px-4 py-2 text-sm rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300"
              >
                Cancel
              </button>
              <button
                onClick={handleApproveAndRun}
                className="px-4 py-2 text-sm rounded bg-blue-600 hover:bg-blue-500 text-white flex items-center gap-1.5"
              >
                <Play size={14} />
                Approve & Run
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Executing overlay */}
      {phase === "executing" && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-zinc-900 border border-zinc-700 rounded-lg px-6 py-5 flex items-center gap-3">
            <Loader2 size={20} className="animate-spin text-blue-400" />
            <span className="text-sm text-zinc-200">Executing approved plan...</span>
          </div>
        </div>
      )}

      {/* Done — show run id */}
      {phase === "done" && (
        <div className="fixed bottom-24 right-6 z-50 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl px-4 py-3 max-w-sm">
          <div className="flex items-start justify-between gap-3 mb-1">
            <span className="text-sm font-medium text-green-400">Plan launched</span>
            <button
              onClick={handleCancel}
              className="text-zinc-400 hover:text-white"
            >
              <X size={14} />
            </button>
          </div>
          <div className="text-xs text-zinc-400">
            Run ID: <span className="font-mono text-zinc-300">{runId}</span>
          </div>
        </div>
      )}

      {/* Error toast */}
      {phase === "error" && error && (
        <div className="fixed bottom-24 right-6 z-50 bg-red-950/90 border border-red-700 rounded-lg shadow-xl px-4 py-3 max-w-sm">
          <div className="flex items-start justify-between gap-3 mb-1">
            <span className="text-sm font-medium text-red-200">Voice error</span>
            <button
              onClick={handleCancel}
              className="text-red-300 hover:text-white"
            >
              <X size={14} />
            </button>
          </div>
          <div className="text-xs text-red-300">{error}</div>
        </div>
      )}

      {/* Settings quick modal */}
      {settingsOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => setSettingsOpen(false)}
        >
          <div
            className="w-full max-w-md bg-zinc-900 border border-zinc-700 rounded-lg shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-800">
              <span className="text-sm font-medium text-zinc-100">Voice settings</span>
              <button
                onClick={() => setSettingsOpen(false)}
                className="text-zinc-400 hover:text-white"
              >
                <X size={18} />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <p className="text-xs text-zinc-400">
                Open the full voice settings page to configure wake word,
                voice, continuous listening, and run a TTS test.
              </p>
              <button
                onClick={goToVoiceSettings}
                className="w-full px-4 py-2 text-sm rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 flex items-center justify-center gap-2"
              >
                <SettingsIcon size={14} />
                Open Voice Settings page
              </button>
            </div>
            <div className="px-5 py-3 border-t border-zinc-800 bg-zinc-950/40">
              <div className="flex items-start gap-2 text-xs text-amber-200">
                <ShieldAlert size={14} className="mt-0.5 flex-shrink-0" />
                <span>
                  Voice commands require approval — security confirmation
                  cannot be bypassed.
                </span>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function RiskBadge({ level, small }: { level: string; small?: boolean }) {
  const colors: Record<string, string> = {
    low: "bg-green-900/60 text-green-300 border-green-800",
    medium: "bg-yellow-900/60 text-yellow-300 border-yellow-800",
    high: "bg-orange-900/60 text-orange-300 border-orange-800",
    critical: "bg-red-900/60 text-red-300 border-red-800",
  };
  const cls = colors[level] || "bg-zinc-800 text-zinc-300 border-zinc-700";
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded border text-xs uppercase tracking-wider ${cls} ${
        small ? "text-[10px]" : ""
      }`}
    >
      {level}
    </span>
  );
}
