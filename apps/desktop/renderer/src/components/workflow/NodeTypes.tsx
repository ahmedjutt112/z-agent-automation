/**
 * Custom React Flow node components — master prompt §34.
 *
 * Each node type renders with:
 *  - a title bar with a node-type icon
 *  - the action / tool name (e.g. "browser.click")
 *  - a summary of args (e.g. `selector: .btn-submit`)
 *  - a status indicator (idle, running, completed, failed)
 *  - Handle connectors on top (target) and bottom (source)
 *
 * The visual kinds are: start, end, action, condition, loop, notification,
 * ai_decision. The canvas dispatches to one of these renderers based on
 * `data.visualType`.
 */

import React from "react";
import { Handle, Position } from "reactflow";
import {
  Play,
  Square,
  MousePointerClick,
  GitBranch,
  Repeat,
  Bell,
  Sparkles,
  CircleDot,
  CheckCircle2,
  Loader2,
  AlertTriangle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

export type NodeVisualType =
  | "start"
  | "end"
  | "action"
  | "condition"
  | "loop"
  | "notification"
  | "ai_decision";

export type NodeStatus = "idle" | "running" | "completed" | "failed";

export interface WorkflowNodeData {
  /** Human-readable label, e.g. "Open Browser". */
  label: string;
  /** The action / tool name, e.g. "browser.click" or "if". */
  toolName: string;
  /** Visual category — controls which renderer is used. */
  visualType: NodeVisualType;
  /** Args summary rendered under the action name. */
  argsSummary?: string;
  /** Live execution status of this node. */
  status?: NodeStatus;
  /** Whether this node is currently selected (canvas highlight). */
  selected?: boolean;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Status badge — shared by every node kind
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: NodeStatus }): JSX.Element {
  switch (status) {
    case "running":
      return (
        <span className="inline-flex items-center gap-1 text-[10px] text-blue-300">
          <Loader2 size={11} className="animate-spin" /> running
        </span>
      );
    case "completed":
      return (
        <span className="inline-flex items-center gap-1 text-[10px] text-emerald-300">
          <CheckCircle2 size={11} /> done
        </span>
      );
    case "failed":
      return (
        <span className="inline-flex items-center gap-1 text-[10px] text-red-300">
          <AlertTriangle size={11} /> failed
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 text-[10px] text-zinc-500">
          <CircleDot size={11} /> idle
        </span>
      );
  }
}

// ---------------------------------------------------------------------------
// Shell — common layout for rectangular nodes
// ---------------------------------------------------------------------------

interface RectProps {
  data: WorkflowNodeData;
  icon: LucideIcon;
  /** Tailwind classes for the header strip + border accent. */
  headerClass: string;
  borderClass: string;
  /** When true the body is shaped like a diamond (rotated square). */
  diamond?: boolean;
  /** When true the body is shaped like a parallelogram. */
  parallelogram?: boolean;
  /** Show only the top + bottom handles; diamonds still get all 4. */
  hideSourceHandle?: boolean;
  hideTargetHandle?: boolean;
}

function NodeShell({
  data,
  icon: Icon,
  headerClass,
  borderClass,
  diamond = false,
  parallelogram = false,
  hideSourceHandle = false,
  hideTargetHandle = false,
}: RectProps): JSX.Element {
  const status: NodeStatus = data.status ?? "idle";
  const selected = data.selected ?? false;

  const shapeClass = diamond
    ? "rounded-md transform rotate-45 w-32 h-32 flex items-center justify-center"
    : parallelogram
      ? "transform -skew-x-12"
      : "rounded-md";

  // For diamond shapes we render the content inside a counter-rotated wrapper
  // so the text stays upright.
  const innerWrapper = diamond ? "transform -rotate-45" : "";

  return (
    <div
      className={[
        "relative border bg-zinc-900/95 shadow-md",
        borderClass,
        selected ? "ring-2 ring-blue-500" : "",
        shapeClass,
      ].join(" ")}
      style={{ minWidth: diamond ? undefined : 200 }}
    >
      {!hideTargetHandle && (
        <Handle
          type="target"
          position={Position.Top}
          className="!w-2.5 !h-2.5 !bg-zinc-500 !border-zinc-700"
        />
      )}
      <div className={diamond ? innerWrapper + " px-3 py-2" : "px-3 py-2"}>
        <div
          className={[
            "flex items-center gap-1.5 px-1 py-0.5 rounded text-[11px] font-medium",
            headerClass,
          ].join(" ")}
        >
          <Icon size={12} />
          <span className="truncate">{data.label}</span>
        </div>
        <div className="mt-1.5 px-1 text-[11px] font-mono text-zinc-300 truncate">
          {data.toolName}
        </div>
        {data.argsSummary && (
          <div className="mt-0.5 px-1 text-[10px] font-mono text-zinc-500 truncate">
            {data.argsSummary}
          </div>
        )}
        <div className="mt-1.5 px-1">
          <StatusBadge status={status} />
        </div>
      </div>
      {!hideSourceHandle && (
        <Handle
          type="source"
          position={Position.Bottom}
          className="!w-2.5 !h-2.5 !bg-zinc-500 !border-zinc-700"
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Concrete node renderers
// ---------------------------------------------------------------------------

export function StartNode({ data }: { data: WorkflowNodeData }): JSX.Element {
  return (
    <div
      className={[
        "relative flex items-center justify-center",
        "w-16 h-16 rounded-full bg-emerald-600/20 border-2 border-emerald-500 text-emerald-300",
        data.selected ? "ring-2 ring-emerald-400" : "",
      ].join(" ")}
    >
      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-3 !h-3 !bg-emerald-400 !border-emerald-700"
      />
      <div className="flex flex-col items-center">
        <Play size={18} />
        <span className="text-[10px] mt-0.5 font-medium">Start</span>
      </div>
    </div>
  );
}

export function EndNode({ data }: { data: WorkflowNodeData }): JSX.Element {
  return (
    <div
      className={[
        "relative flex items-center justify-center",
        "w-16 h-16 rounded-full bg-red-600/20 border-2 border-red-500 text-red-300",
        data.selected ? "ring-2 ring-red-400" : "",
      ].join(" ")}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-red-400 !border-red-700"
      />
      <div className="flex flex-col items-center">
        <Square size={18} />
        <span className="text-[10px] mt-0.5 font-medium">End</span>
      </div>
    </div>
  );
}

export function ActionNode({ data }: { data: WorkflowNodeData }): JSX.Element {
  return (
    <NodeShell
      data={data}
      icon={MousePointerClick}
      headerClass="bg-blue-600/30 text-blue-200"
      borderClass="border-blue-700/60"
    />
  );
}

export function ConditionNode({ data }: { data: WorkflowNodeData }): JSX.Element {
  return (
    <NodeShell
      data={data}
      icon={GitBranch}
      headerClass="bg-yellow-500/30 text-yellow-200"
      borderClass="border-yellow-500/60"
      diamond
    />
  );
}

export function LoopNode({ data }: { data: WorkflowNodeData }): JSX.Element {
  return (
    <NodeShell
      data={data}
      icon={Repeat}
      headerClass="bg-purple-600/30 text-purple-200"
      borderClass="border-purple-600/60"
      parallelogram
    />
  );
}

export function NotificationNode({ data }: { data: WorkflowNodeData }): JSX.Element {
  return (
    <NodeShell
      data={data}
      icon={Bell}
      headerClass="bg-orange-600/30 text-orange-200"
      borderClass="border-orange-600/60"
    />
  );
}

export function AIDecisionNode({ data }: { data: WorkflowNodeData }): JSX.Element {
  return (
    <div
      className={[
        "relative border bg-gradient-to-br from-blue-900/60 to-purple-900/60 rounded-md shadow-md",
        "border-purple-500/60",
        data.selected ? "ring-2 ring-purple-400" : "",
      ].join(" ")}
      style={{ minWidth: 200 }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-2.5 !h-2.5 !bg-purple-400 !border-purple-700"
      />
      <div className="px-3 py-2">
        <div className="flex items-center gap-1.5 px-1 py-0.5 rounded text-[11px] font-medium bg-purple-500/30 text-purple-100">
          <Sparkles size={12} />
          <span className="truncate">{data.label}</span>
        </div>
        <div className="mt-1.5 px-1 text-[11px] font-mono text-zinc-200 truncate">
          {data.toolName}
        </div>
        {data.argsSummary && (
          <div className="mt-0.5 px-1 text-[10px] font-mono text-zinc-400 truncate">
            {data.argsSummary}
          </div>
        )}
        <div className="mt-1.5 px-1">
          <StatusBadge status={data.status ?? "idle"} />
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-2.5 !h-2.5 !bg-purple-400 !border-purple-700"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Registry — used by React Flow's `nodeTypes` prop
// ---------------------------------------------------------------------------

export const workflowNodeTypes = {
  start: StartNode,
  end: EndNode,
  action: ActionNode,
  condition: ConditionNode,
  loop: LoopNode,
  notification: NotificationNode,
  ai_decision: AIDecisionNode,
} as const;

/** Render the right component for a given visual type key. */
export function renderNodeByVisualType(
  visualType: NodeVisualType,
  data: WorkflowNodeData,
): JSX.Element {
  switch (visualType) {
    case "start":
      return <StartNode data={data} />;
    case "end":
      return <EndNode data={data} />;
    case "condition":
      return <ConditionNode data={data} />;
    case "loop":
      return <LoopNode data={data} />;
    case "notification":
      return <NotificationNode data={data} />;
    case "ai_decision":
      return <AIDecisionNode data={data} />;
    case "action":
    default:
      return <ActionNode data={data} />;
  }
}
