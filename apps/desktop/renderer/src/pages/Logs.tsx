/** Logs page — master prompt §37, §38. */

export function Logs() {
  return (
    <div>
      <h1 className="text-2xl font-semibold mb-4">Logs</h1>
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 font-mono text-xs">
        <div className="text-zinc-500">// Structured logs from the automation service will stream here via WebSocket</div>
        <div className="text-zinc-500">// Connect to ws://127.0.0.1:8765/events to subscribe</div>
      </div>
    </div>
  );
}
