import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
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
    const [testResult, setTestResult] = useState(null);
    const [autoListenBusy, setAutoListenBusy] = useState(false);
    // Load current status on mount.
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const s = await api.voice.status();
                if (cancelled)
                    return;
                setMockMode(s.mock_mode);
                setListening(s.listening);
                if (s.wake_word)
                    setWakeWord(s.wake_word);
                setAutoListen(s.listening);
            }
            catch {
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
        }
        catch {
            setTestResult("err");
        }
        finally {
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
            }
            else {
                await api.voice.startContinuous();
                setAutoListen(true);
                setListening(true);
            }
        }
        catch {
            // ignore for now — surfaced via status polling
        }
        finally {
            setAutoListenBusy(false);
        }
    }
    return (_jsxs("div", { children: [_jsxs("div", { className: "flex items-center justify-between mb-4", children: [_jsxs("h1", { className: "text-2xl font-semibold flex items-center gap-2", children: [_jsx(Mic, { size: 22, className: "text-blue-400" }), "Voice Settings"] }), mockMode && (_jsx("span", { className: "text-xs px-2 py-1 rounded bg-amber-950/60 border border-amber-700 text-amber-300", children: "Mock mode active \u2014 no real audio captured" }))] }), _jsxs("div", { className: "mb-6 flex items-start gap-2 text-sm text-amber-200 bg-amber-950/30 border border-amber-800 rounded-lg px-4 py-3", children: [_jsx(ShieldAlert, { size: 16, className: "mt-0.5 flex-shrink-0" }), _jsxs("div", { children: [_jsx("strong", { children: "Permission required." }), " Voice commands never bypass the security confirmation flow. Even in continuous mode, every plan requires explicit user approval before execution."] })] }), _jsxs("div", { className: "space-y-4 max-w-2xl", children: [_jsx(SettingRow, { label: "Wake word", hint: "Say this word before issuing a command in continuous mode", children: _jsx("input", { type: "text", value: wakeWord, onChange: (e) => setWakeWord(e.target.value), placeholder: "computer", className: "bg-zinc-950 border border-zinc-700 rounded px-3 py-2 text-sm text-zinc-100 w-full focus:outline-none focus:border-blue-500" }) }), _jsx(SettingRow, { label: "Voice", hint: "Voice used for text-to-speech output", children: _jsxs("select", { value: voice, onChange: (e) => setVoice(e.target.value), className: "bg-zinc-950 border border-zinc-700 rounded px-3 py-2 text-sm text-zinc-100 w-full focus:outline-none focus:border-blue-500", children: [_jsx("option", { value: "default", children: "Default (warm, friendly \u2014 tongtong)" }), _jsx("option", { value: "male", children: "Male (calm, professional \u2014 xiaochen)" }), _jsx("option", { value: "female", children: "Female (warm, friendly \u2014 tongtong)" }), _jsx("option", { value: "tongtong", children: "tongtong (named)" }), _jsx("option", { value: "chuichui", children: "chuichui (named)" }), _jsx("option", { value: "xiaochen", children: "xiaochen (named)" }), _jsx("option", { value: "jam", children: "jam (named)" }), _jsx("option", { value: "kazi", children: "kazi (named)" }), _jsx("option", { value: "douji", children: "douji (named)" }), _jsx("option", { value: "luodo", children: "luodo (named)" })] }) }), _jsx(SettingRow, { label: "Auto-listen (continuous mode)", hint: "Listen for the wake word in the background", children: _jsxs("div", { className: "flex items-center gap-3", children: [_jsx("button", { onClick: toggleAutoListen, disabled: autoListenBusy, className: `relative w-12 h-6 rounded-full transition-colors ${autoListen ? "bg-blue-600" : "bg-zinc-700"} ${autoListenBusy ? "opacity-50" : ""}`, children: _jsx("span", { className: `absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${autoListen ? "translate-x-6" : ""}` }) }), _jsx("span", { className: "text-xs text-zinc-400", children: listening ? (_jsxs("span", { className: "flex items-center gap-1 text-green-400", children: [_jsx(Radio, { size: 12, className: "animate-pulse" }), "Listening for wake word \"", wakeWord, "\""] })) : ("Off") })] }) }), _jsx(SettingRow, { label: "Test voice output", hint: 'Speaks "Hello, voice control is working" using the selected voice', children: _jsxs("div", { className: "flex items-center gap-3", children: [_jsxs("button", { onClick: handleTest, disabled: testing, className: "px-4 py-2 text-sm rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-100 flex items-center gap-2 disabled:opacity-50", children: [testing ? (_jsx(Loader2, { size: 14, className: "animate-spin" })) : (_jsx(Volume2, { size: 14 })), testing ? "Speaking..." : "Test voice"] }), testResult === "ok" && (_jsxs("span", { className: "text-xs text-green-400 flex items-center gap-1", children: [_jsx(CheckCircle2, { size: 12 }), "Spoken successfully"] })), testResult === "err" && (_jsx("span", { className: "text-xs text-red-400", children: "Test failed \u2014 check service is running" }))] }) }), _jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg p-4", children: [_jsxs("div", { className: "text-sm font-medium mb-1 flex items-center gap-2", children: [_jsx(Radio, { size: 14, className: "text-amber-400" }), "Mode"] }), _jsx("div", { className: "text-xs text-zinc-400", children: mockMode ? (_jsxs(_Fragment, { children: [_jsx("strong", { className: "text-amber-300", children: "Mock mode" }), " \u2014 voice capture and synthesis return deterministic test data without touching audio hardware. Disable mock mode in", _jsx("code", { className: "text-zinc-300 mx-1 bg-zinc-950 px-1 rounded", children: ".env" }), "(", _jsx("code", { className: "text-zinc-300 bg-zinc-950 px-1 rounded", children: "AUTOMATION_MOCK_MODE=false" }), ") to use the real microphone + Z.ai ASR / TTS APIs."] })) : (_jsxs(_Fragment, { children: [_jsx("strong", { className: "text-green-300", children: "Live mode" }), " \u2014 the microphone and speaker will be used for STT and TTS. Requires the ", _jsx("code", { className: "text-zinc-300 bg-zinc-950 px-1 rounded", children: "z-ai" }), "CLI (", _jsx("code", { className: "text-zinc-300 bg-zinc-950 px-1 rounded", children: "npm install -g z-ai-web-dev-sdk" }), ") and ", _jsx("code", { className: "text-zinc-300 bg-zinc-950 px-1 rounded", children: "sounddevice" }), "+ ", _jsx("code", { className: "text-zinc-300 bg-zinc-950 px-1 rounded", children: "soundfile" }), "Python packages."] })) })] }), _jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg p-4", children: [_jsx("div", { className: "text-sm font-medium mb-2", children: "Permission flow" }), _jsxs("ol", { className: "text-xs text-zinc-400 space-y-1 list-decimal list-inside", children: [_jsx("li", { children: "You speak a command (e.g. \"open chrome and search for AI\")" }), _jsx("li", { children: "Speech-to-text transcribes the audio" }), _jsx("li", { children: "AI planner generates a structured plan with risk levels" }), _jsx("li", { children: "Plan is displayed for explicit review" }), _jsxs("li", { children: [_jsx("strong", { className: "text-zinc-200", children: "You click \"Approve & Run\"" }), " ", "\u2014 even for low-risk plans, voice never bypasses this step"] }), _jsx("li", { children: "Permission engine re-evaluates the plan (defense in depth)" }), _jsx("li", { children: "Automation engine executes step-by-step" })] })] })] })] }));
}
function SettingRow({ label, hint, children, }) {
    return (_jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg p-4", children: [_jsx("div", { className: "flex items-start justify-between gap-4 mb-2", children: _jsxs("div", { children: [_jsx("div", { className: "text-sm font-medium", children: label }), hint && _jsx("div", { className: "text-xs text-zinc-500 mt-0.5", children: hint })] }) }), children] }));
}
