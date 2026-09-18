/** AI Agent chat screen — master prompt §32. */

import { useState } from "react";
import { api, Plan } from "../lib/api";

interface Message {
  role: "user" | "ai";
  content: string;
  plan?: Plan;
}

export function AIAgent() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    { role: "ai", content: "Hi! Describe what you'd like me to automate. Try something like:\n\n\"Open Chrome, search for AI automation, take a screenshot of the first result, and save it to my Desktop.\"" },
  ]);
  const [loading, setLoading] = useState(false);

  async function send() {
    if (!input.trim() || loading) return;
    const userMsg = input;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setLoading(true);
    try {
      const plan = await api.createPlan(userMsg);
      setMessages((prev) => [
        ...prev,
        {
          role: "ai",
          content: `Plan generated (${plan.steps.length} steps, risk: ${plan.overall_risk}, est. ${plan.estimated_duration_seconds}s)`,
          plan,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "ai", content: `Error: ${(err as Error).message}` },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function runPlan(plan: Plan) {
    try {
      const result = await api.runPlan(plan);
      setMessages((prev) => [
        ...prev,
        { role: "ai", content: `Started run: ${result.run_id}` },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "ai", content: `Failed to start: ${(err as Error).message}` },
      ]);
    }
  }

  return (
    <div className="flex flex-col h-full">
      <h1 className="text-2xl font-semibold mb-4">AI Agent</h1>
      <div className="flex-1 overflow-auto space-y-3">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`p-3 rounded-lg max-w-3xl ${
              msg.role === "user"
                ? "bg-blue-900 ml-auto"
                : "bg-zinc-800 mr-auto"
            }`}
          >
            <div className="text-xs uppercase text-zinc-400 mb-1">{msg.role}</div>
            <div className="text-sm whitespace-pre-wrap">{msg.content}</div>
            {msg.plan && (
              <div className="mt-3 bg-zinc-900 rounded p-3 border border-zinc-700">
                <div className="text-xs text-zinc-400 mb-2">Proposed Plan:</div>
                <ol className="text-sm space-y-1">
                  {msg.plan.steps.map((s) => (
                    <li key={s.id}>
                      <span className="text-zinc-500">#{s.id}</span>{" "}
                      <span className="font-mono text-xs bg-zinc-700 px-1 rounded">{s.action}</span>
                      {"  "}
                      <span className={`text-xs ${
                        s.risk_level === "critical" ? "text-red-400" :
                        s.risk_level === "high" ? "text-amber-400" :
                        s.risk_level === "medium" ? "text-yellow-400" :
                        "text-emerald-400"
                      }`}>
                        [{s.risk_level}]
                      </span>
                    </li>
                  ))}
                </ol>
                <button
                  onClick={() => runPlan(msg.plan!)}
                  className="mt-3 bg-emerald-600 hover:bg-emerald-500 px-3 py-1.5 rounded text-xs font-medium"
                >
                  Run Plan
                </button>
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="text-zinc-500 text-sm animate-pulse">Thinking...</div>
        )}
      </div>
      <div className="mt-3 flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Ask AI to automate something..."
          className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
        />
        <button
          onClick={send}
          disabled={loading}
          className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium"
        >
          Send
        </button>
      </div>
    </div>
  );
}
