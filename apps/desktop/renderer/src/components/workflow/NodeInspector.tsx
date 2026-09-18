/**
 * Node Inspector — right sidebar showing properties of the selected node.
 * Master prompt §34 — Inspector (right).
 *
 * Renders dynamic args fields based on the node type, plus the common
 * fields: timeout, retry count, risk level, on-error action. All inputs are
 * controlled and call back to the parent via `onChange`.
 */

import React from "react";
import { Trash2, AlertTriangle } from "lucide-react";
import type {
  OnErrorAction,
  RiskLevel,
  WorkflowNode,
} from "../../lib/api";
import { PALETTE_CATEGORIES } from "./NodePalette";
import type { NodeVisualType } from "./NodeTypes";

// ---------------------------------------------------------------------------
// Args schema — declarative spec for the dynamic form
// ---------------------------------------------------------------------------

type ArgFieldType = "text" | "textarea" | "number" | "checkbox";

interface ArgFieldSpec {
  key: string;
  label: string;
  type: ArgFieldType;
  placeholder?: string;
}

const COMMON_FIELDS: Record<string, ArgFieldSpec[]> = {
  "browser.open":     [{ key: "browser", label: "Browser", type: "text", placeholder: "chrome" }],
  "browser.navigate": [{ key: "url", label: "URL", type: "text", placeholder: "https://..." }],
  "browser.click":    [{ key: "selector", label: "Selector", type: "text", placeholder: "button.submit" }],
  "browser.type":     [
    { key: "selector", label: "Selector", type: "text" },
    { key: "text", label: "Text", type: "text" },
  ],
  "browser.extract":  [
    { key: "selector", label: "Selector", type: "text" },
    { key: "fields", label: "Fields (comma-separated)", type: "text" },
  ],
  "browser.download": [{ key: "url", label: "URL", type: "text" }],

  "app.launch": [{ key: "path", label: "Executable path", type: "text" }],
  "app.close":   [{ key: "name", label: "Process name", type: "text" }],
  "mouse.click": [
    { key: "x", label: "X", type: "number" },
    { key: "y", label: "Y", type: "number" },
  ],
  "keyboard.type":  [{ key: "text", label: "Text", type: "textarea" }],
  "keyboard.hotkey":[{ key: "keys", label: "Keys (comma-separated)", type: "text", placeholder: "ctrl,c" }],
  "wait":           [{ key: "seconds", label: "Seconds", type: "number" }],

  "screen.capture":  [],
  "screen.ocr":      [{ key: "region", label: "Region", type: "text", placeholder: "full or x,y,w,h" }],
  "vision.find_image":[{ key: "image_path", label: "Image path", type: "text" }],
  "vision.find_text": [{ key: "text", label: "Search text", type: "text" }],

  "file.read":   [{ key: "path", label: "Path", type: "text" }],
  "file.write":  [
    { key: "path", label: "Path", type: "text" },
    { key: "content", label: "Content", type: "textarea" },
  ],
  "file.move":   [
    { key: "src", label: "Source", type: "text" },
    { key: "dst", label: "Destination", type: "text" },
  ],
  "file.rename": [
    { key: "path", label: "Path", type: "text" },
    { key: "new_name", label: "New name", type: "text" },
  ],
  "file.copy":   [
    { key: "src", label: "Source", type: "text" },
    { key: "dst", label: "Destination", type: "text" },
  ],

  "if":          [{ key: "condition", label: "Condition (JSON)", type: "textarea" }],
  "for_each":    [
    { key: "loop", label: "Loop spec (JSON)", type: "textarea" },
    { key: "action", label: "Inner action", type: "text" },
  ],
  "while":       [{ key: "loop", label: "Loop spec (JSON)", type: "textarea" }],
  "wait_until":  [{ key: "timeout_ms", label: "Timeout (ms)", type: "number" }],
  "retry":       [{ key: "attempts", label: "Attempts", type: "number" }],
  "error_handler": [{ key: "on_error_action", label: "On error", type: "text" }],

  "ai.decision": [
    { key: "prompt", label: "Prompt", type: "textarea" },
    { key: "provider", label: "Provider", type: "text", placeholder: "openai" },
  ],
  "ai.ask_user": [{ key: "prompt", label: "Prompt", type: "textarea" }],
  "approval.request": [{ key: "summary", label: "Summary", type: "textarea" }],

  "code.run_command": [{ key: "command", label: "Command", type: "textarea" }],
  "code.run_python":  [{ key: "script", label: "Python script", type: "textarea" }],

  "notify.email":   [
    { key: "to", label: "To", type: "text" },
    { key: "subject", label: "Subject", type: "text" },
    { key: "body", label: "Body", type: "textarea" },
  ],
  "notify.webhook":  [
    { key: "url", label: "URL", type: "text" },
    { key: "method", label: "Method", type: "text" },
  ],

  "start": [],
  "end":   [],
};

function fieldsFor(toolName: string): ArgFieldSpec[] {
  return COMMON_FIELDS[toolName] ?? [];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function readArg(value: unknown, type: ArgFieldType): string {
  if (value === null || value === undefined) return "";
  if (type === "textarea") {
    return typeof value === "string"
      ? value
      : JSON.stringify(value, null, 2);
  }
  if (type === "number") {
    return typeof value === "number" ? String(value) : "";
  }
  if (type === "checkbox") {
    return value ? "true" : "false";
  }
  if (Array.isArray(value)) return value.join(",");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function writeArg(prev: unknown, raw: string, type: ArgFieldType): unknown {
  if (type === "number") {
    if (raw === "") return 0;
    const n = Number(raw);
    return Number.isFinite(n) ? n : prev;
  }
  if (type === "checkbox") return raw === "true";
  if (type === "textarea") {
    // Try to parse JSON for structured fields like condition/loop.
    const trimmed = raw.trim();
    if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
      try {
        return JSON.parse(trimmed);
      } catch {
        return raw;
      }
    }
    return raw;
  }
  // For text fields that look like comma-separated lists.
  if (raw.includes(",") && (raw.includes("[") || !raw.includes(" "))) {
    // Heuristic — leave as string; backend can parse.
    return raw;
  }
  return raw;
}

// ---------------------------------------------------------------------------
// Inspector component
// ---------------------------------------------------------------------------

export interface NodeInspectorProps {
  node: WorkflowNode | null;
  onChange: (patch: Partial<WorkflowNode>) => void;
  onDelete: (nodeId: string) => void;
}

const VISUAL_TYPE_LABELS: Record<NodeVisualType, string> = {
  start: "Start",
  end: "End",
  action: "Action",
  condition: "Condition",
  loop: "Loop",
  notification: "Notification",
  ai_decision: "AI Decision",
};

export function NodeInspector({ node, onChange, onDelete }: NodeInspectorProps): JSX.Element {
  if (!node) {
    return (
      <aside className="w-80 shrink-0 border-l border-zinc-800 bg-zinc-950/70 p-4 text-sm text-zinc-500">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-400 mb-2">
          Inspector
        </h2>
        <p className="text-xs">
          Select a node on the canvas to edit its properties.
        </p>
      </aside>
    );
  }

  // Build the list of alternative tool names within the same visual category
  // so the dropdown only allows switching to visually-compatible nodes.
  const sameCategory = PALETTE_CATEGORIES
    .flatMap((c) => c.items)
    .filter((i) => i.visualType === (node.visual_type ?? "action"));
  const typeOptions = Array.from(
    new Map(sameCategory.map((i) => [i.toolName, i])).values(),
  );

  const visualType = node.visual_type ?? "action";
  const fields = fieldsFor(node.type);

  return (
    <aside className="w-80 shrink-0 border-l border-zinc-800 bg-zinc-950/70 overflow-y-auto h-full">
      <div className="px-3 py-2 sticky top-0 bg-zinc-950/95 backdrop-blur border-b border-zinc-800 z-10">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
          Inspector
        </h2>
      </div>

      <div className="p-3 space-y-3">
        {/* Node ID (read-only) */}
        <div>
          <label className="block text-[11px] font-medium text-zinc-400 mb-0.5">
            Node ID
          </label>
          <input
            type="text"
            value={node.id}
            readOnly
            className="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-500 font-mono"
          />
        </div>

        {/* Node type dropdown — only swaps within same visual category */}
        <div>
          <label className="block text-[11px] font-medium text-zinc-400 mb-0.5">
            Type ({VISUAL_TYPE_LABELS[visualType]})
          </label>
          <select
            value={node.type}
            onChange={(e) => {
              const next = e.target.value;
              const match = typeOptions.find((o) => o.toolName === next);
              onChange({
                type: next,
                label: match?.label ?? node.label,
                args: match?.defaultArgs ?? node.args,
              });
            }}
            className="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200"
          >
            {typeOptions.length === 0 ? (
              <option value={node.type}>{node.type}</option>
            ) : (
              typeOptions.map((o) => (
                <option key={o.toolName} value={o.toolName}>
                  {o.label} ({o.toolName})
                </option>
              ))
            )}
          </select>
        </div>

        {/* Label */}
        <div>
          <label className="block text-[11px] font-medium text-zinc-400 mb-0.5">
            Label
          </label>
          <input
            type="text"
            value={node.label ?? ""}
            onChange={(e) => onChange({ label: e.target.value })}
            className="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200"
          />
        </div>

        {/* Dynamic args form */}
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1">
            Arguments
          </div>
          {fields.length === 0 ? (
            <p className="text-[11px] text-zinc-500 italic">
              No arguments for this node type.
            </p>
          ) : (
            <div className="space-y-2">
              {fields.map((f) => {
                const raw = readArg(node.args[f.key], f.type);
                return (
                  <div key={f.key}>
                    <label className="block text-[11px] font-medium text-zinc-400 mb-0.5">
                      {f.label}
                    </label>
                    {f.type === "textarea" ? (
                      <textarea
                        rows={4}
                        value={raw}
                        placeholder={f.placeholder}
                        onChange={(e) => {
                          const next = { ...node.args };
                          next[f.key] = writeArg(next[f.key], e.target.value, f.type);
                          onChange({ args: next });
                        }}
                        className="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200 font-mono"
                      />
                    ) : (
                      <input
                        type={f.type === "number" ? "number" : "text"}
                        value={raw}
                        placeholder={f.placeholder}
                        onChange={(e) => {
                          const next = { ...node.args };
                          next[f.key] = writeArg(next[f.key], e.target.value, f.type);
                          onChange({ args: next });
                        }}
                        className="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200 font-mono"
                      />
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Common fields */}
        <div className="border-t border-zinc-800 pt-3 space-y-2">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
            Execution
          </div>

          <div>
            <label className="block text-[11px] font-medium text-zinc-400 mb-0.5">
              Timeout (ms)
            </label>
            <input
              type="number"
              value={node.timeout_ms}
              onChange={(e) => onChange({ timeout_ms: Number(e.target.value) || 0 })}
              className="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200 font-mono"
            />
          </div>

          <div>
            <label className="block text-[11px] font-medium text-zinc-400 mb-0.5">
              Retry count
            </label>
            <input
              type="number"
              value={node.retry_count}
              onChange={(e) => onChange({ retry_count: Number(e.target.value) || 0 })}
              className="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200 font-mono"
            />
          </div>

          <div>
            <label className="block text-[11px] font-medium text-zinc-400 mb-0.5">
              Risk level
            </label>
            <select
              value={node.risk_level ?? "low"}
              onChange={(e) => onChange({ risk_level: e.target.value as RiskLevel })}
              className="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200"
            >
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-medium text-zinc-400 mb-0.5">
              On error
            </label>
            <select
              value={node.on_error_action ?? "stop"}
              onChange={(e) =>
                onChange({ on_error_action: e.target.value as OnErrorAction })
              }
              className="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200"
            >
              <option value="stop">stop</option>
              <option value="continue">continue</option>
              <option value="jump_to">jump_to</option>
              <option value="retry">retry</option>
            </select>
            {node.on_error_action === "jump_to" && (
              <input
                type="text"
                value={node.on_error ?? ""}
                placeholder="target node id"
                onChange={(e) => onChange({ on_error: e.target.value })}
                className="mt-1 w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200 font-mono"
              />
            )}
          </div>
        </div>

        {/* Danger zone */}
        <div className="border-t border-zinc-800 pt-3">
          <button
            type="button"
            onClick={() => onDelete(node.id)}
            className="inline-flex items-center gap-1 text-xs text-red-300 hover:text-red-200 px-2 py-1 rounded border border-red-900 hover:bg-red-950/50"
          >
            <Trash2 size={12} /> Delete node
          </button>
        </div>

        {/* Helpful hint about extra args */}
        <div className="text-[10px] text-zinc-600 flex items-start gap-1 pt-2 border-t border-zinc-800">
          <AlertTriangle size={10} className="mt-0.5 shrink-0" />
          <span>
            Extra args not shown above can be edited by exporting the
            workflow JSON. Visual metadata (position, label) is preserved
            automatically.
          </span>
        </div>
      </div>
    </aside>
  );
}
