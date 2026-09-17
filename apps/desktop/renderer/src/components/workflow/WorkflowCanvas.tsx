/**
 * WorkflowCanvas — master prompt §20 (node types), §34 (workflow editor UI).
 *
 * The main React Flow canvas. Loads a workflow by ID (or starts a new one),
 * renders all nodes with their positions, supports drag-to-move,
 * click-to-select, and edge drawing. Top toolbar exposes Save / Run /
 * Delete / Duplicate / Rename.
 *
 * State:
 *  - Local React state for nodes + edges (via useNodesState / useEdgesState).
 *  - On Save: serialize to Workflow pydantic shape, call api.saveWorkflow() or
 *    api.updateWorkflow().
 *  - On Run: call api.runWorkflow(id) and emit the result via onRunLaunched.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  ConnectionLineType,
  Controls,
  MiniMap,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  type OnSelectionChangeParams,
  MarkerType,
} from "reactflow";
import "reactflow/dist/style.css";
import {
  Save,
  Play,
  Trash2,
  Copy,
  Loader2,
  Check,
  AlertTriangle,
  Lock,
  Unlock,
} from "lucide-react";

import { api } from "../../lib/api";
import type { Workflow, WorkflowNode } from "../../lib/api";
import { workflowNodeTypes, type NodeVisualType, type WorkflowNodeData } from "./NodeTypes";
import { NodePalette, PALETTE_DRAG_TYPE, type PaletteDragPayload } from "./NodePalette";
import { NodeInspector } from "./NodeInspector";

// ---------------------------------------------------------------------------
// Edge styles
// ---------------------------------------------------------------------------

const EDGE_STYLES: Record<string, React.CSSProperties> = {
  default:    { stroke: "#71717a", strokeWidth: 1.5 },
  conditional:{ stroke: "#eab308", strokeWidth: 1.5, strokeDasharray: "5 5" },
  error:      { stroke: "#ef4444", strokeWidth: 1.5 },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let _nodeIdCounter = 0;
function nextNodeId(prefix = "n"): string {
  _nodeIdCounter += 1;
  return `${prefix}_${Date.now().toString(36)}_${_nodeIdCounter}`;
}

function summarizeArgs(args: Record<string, unknown>): string {
  const keys = Object.keys(args).filter((k) => !k.startsWith("_"));
  if (keys.length === 0) return "";
  const parts = keys.slice(0, 2).map((k) => {
    const v = args[k];
    let s: string;
    if (v === null || v === undefined) s = "";
    else if (typeof v === "string") s = v.length > 24 ? v.slice(0, 24) + "..." : v;
    else if (typeof v === "number" || typeof v === "boolean") s = String(v);
    else s = JSON.stringify(v);
    return `${k}: ${s}`;
  });
  if (keys.length > 2) parts.push(`+${keys.length - 2} more`);
  return parts.join(", ");
}

function workflowNodeToFlowNode(node: WorkflowNode): Node<WorkflowNodeData> {
  const visualType: NodeVisualType = (node.visual_type ?? "action") as NodeVisualType;
  const data: WorkflowNodeData = {
    label: node.label ?? node.type,
    toolName: node.type,
    visualType,
    argsSummary: summarizeArgs(node.args),
    status: "idle",
    selected: false,
  };
  return {
    id: node.id,
    type: visualType,
    position: node.position ?? { x: 0, y: 0 },
    data,
  };
}

// ---------------------------------------------------------------------------
// New-workflow factory
// ---------------------------------------------------------------------------

function emptyWorkflow(): Workflow {
  const now = new Date().toISOString();
  const id = `wf_${Date.now().toString(36)}`;
  return {
    id,
    name: "Untitled Workflow",
    version: 1,
    description: null,
    trigger: { type: "manual", timezone: "UTC" },
    nodes: [],
    variables: {},
    enabled: true,
    created_at: now,
    updated_at: now,
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface WorkflowCanvasProps {
  workflowId: string;
  /** Called after the user triggers Run so the parent can navigate. */
  onRunLaunched?: (runId: string, workflowId: string) => void;
  onBackToList?: () => void;
}

export function WorkflowCanvas({
  workflowId,
  onRunLaunched,
  onBackToList,
}: WorkflowCanvasProps): JSX.Element {
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("Untitled Workflow");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);
  const [busy, setBusy] = useState<"idle" | "save" | "run" | "delete" | "duplicate">("idle");
  const [toast, setToast] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  // Source-of-truth workflow nodes — the canvas derives React Flow nodes
  // from this and writes inspector edits back into it.
  const wfNodesRef = useRef<Record<string, WorkflowNode>>({});

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<WorkflowNodeData>([]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState([]);

  // -------------------------------------------------------------------------
  // Load workflow on mount / when workflowId changes
  // -------------------------------------------------------------------------

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    async function load(): Promise<void> {
      if (workflowId === "new") {
        const wf = emptyWorkflow();
        if (cancelled) return;
        setWorkflow(wf);
        setName(wf.name);
        wfNodesRef.current = {};
        setRfNodes([]);
        setRfEdges([]);
        setLoading(false);
        return;
      }
      try {
        const wf = await api.getWorkflow(workflowId);
        if (cancelled) return;
        setWorkflow(wf);
        setName(wf.name);
        const map: Record<string, WorkflowNode> = {};
        for (const n of wf.nodes) map[n.id] = n;
        wfNodesRef.current = map;
        setRfNodes(wf.nodes.map(workflowNodeToFlowNode));
        // Derive edges from node.next / node.on_error
        const edges: Edge[] = [];
        for (const n of wf.nodes) {
          if (n.next) {
            edges.push({
              id: `e_${n.id}__${n.next}`,
              source: n.id,
              target: n.next,
              type: "default",
              style: EDGE_STYLES.default,
              markerEnd: { type: MarkerType.ArrowClosed, color: "#71717a" },
            });
          }
          if (n.on_error) {
            edges.push({
              id: `e_${n.id}__err__${n.on_error}`,
              source: n.id,
              target: n.on_error,
              type: "error",
              style: EDGE_STYLES.error,
              animated: true,
              markerEnd: { type: MarkerType.ArrowClosed, color: "#ef4444" },
            });
          }
        }
        setRfEdges(edges);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (cancelled) return;
        setError(msg);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [workflowId, setRfNodes, setRfEdges]);

  // -------------------------------------------------------------------------
  // Toast helper
  // -------------------------------------------------------------------------

  const flashToast = useCallback((kind: "ok" | "err", msg: string) => {
    setToast({ kind, msg });
    window.setTimeout(() => setToast(null), 2400);
  }, []);

  // -------------------------------------------------------------------------
  // Selection — sync selectedNodeId + visual ring on the React Flow node
  // -------------------------------------------------------------------------

  useEffect(() => {
    setRfNodes((nodes) =>
      nodes.map((n) => ({ ...n, data: { ...n.data, selected: n.id === selectedNodeId } })),
    );
  }, [selectedNodeId, setRfNodes]);

  const onSelectionChange = useCallback(
    (params: OnSelectionChangeParams) => {
      if (params.nodes.length === 0) {
        setSelectedNodeId(null);
      } else {
        const first = params.nodes[0] as Node<WorkflowNodeData>;
        setSelectedNodeId(first.id);
      }
    },
    [],
  );

  // -------------------------------------------------------------------------
  // Drop handler — accept palette items dragged onto the canvas
  // -------------------------------------------------------------------------

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>): void => {
      e.preventDefault();
      if (locked) return;
      const raw = e.dataTransfer.getData(PALETTE_DRAG_TYPE);
      if (!raw) return;
      let payload: PaletteDragPayload;
      try {
        payload = JSON.parse(raw) as PaletteDragPayload;
      } catch {
        return;
      }
      const id = nextNodeId(payload.toolName.replace(/\./g, "_"));
      // Position the new node near the mouse cursor. React Flow's screenToFlowPosition
      // is exposed on the wrapper instance via onInit; for simplicity we use a
      // staggered default position based on existing node count.
      const offset = rfNodes.length * 32;
      const pos = { x: 220 + offset, y: 120 + offset };
      const wfNode: WorkflowNode = {
        id,
        type: payload.toolName,
        args: { ...(payload.defaultArgs ?? {}) },
        next: null,
        on_error: null,
        timeout_ms: 30_000,
        retry_count: 0,
        retry_delay_ms: 1000,
        position: pos,
        visual_type: payload.visualType,
        label: payload.label,
      };
      wfNodesRef.current[id] = wfNode;
      setRfNodes((nodes) => [...nodes, workflowNodeToFlowNode(wfNode)]);
    },
    [locked, rfNodes.length, setRfNodes],
  );

  const onDragOver = useCallback((e: React.DragEvent<HTMLDivElement>): void => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  // -------------------------------------------------------------------------
  // Edge creation
  // -------------------------------------------------------------------------

  const onConnect = useCallback(
    (params: Connection) => {
      setRfEdges((eds) => addEdge(
        {
          ...params,
          type: "default",
          style: EDGE_STYLES.default,
          markerEnd: { type: MarkerType.ArrowClosed, color: "#71717a" },
        },
        eds,
      ));
      // Also persist into the source node's `next` field so save serializes it.
      if (params.source && params.target) {
        const src = wfNodesRef.current[params.source];
        if (src) {
          wfNodesRef.current[params.source] = { ...src, next: params.target };
        }
      }
    },
    [setRfEdges],
  );

  // -------------------------------------------------------------------------
  // Sync node position changes back into wfNodesRef
  // -------------------------------------------------------------------------

  const onNodesChangeWrapped = useCallback(
    (changes: NodeChange[]) => {
      onNodesChange(changes);
      for (const ch of changes) {
        if (ch.type === "position" && ch.position && !ch.dragging) {
          const n = wfNodesRef.current[ch.id];
          if (n) {
            wfNodesRef.current[ch.id] = {
              ...n,
              position: { x: ch.position.x, y: ch.position.y },
            };
          }
        }
        if (ch.type === "remove") {
          delete wfNodesRef.current[ch.id];
          // Also clear any `next`/`on_error` references pointing to it.
          for (const [nid, node] of Object.entries(wfNodesRef.current)) {
            if (node.next === ch.id) {
              wfNodesRef.current[nid] = { ...node, next: null };
            }
            if (node.on_error === ch.id) {
              wfNodesRef.current[nid] = { ...node, on_error: null };
            }
          }
          if (selectedNodeId === ch.id) setSelectedNodeId(null);
        }
      }
    },
    [onNodesChange, selectedNodeId],
  );

  // -------------------------------------------------------------------------
  // Inspector callbacks
  // -------------------------------------------------------------------------

  const onInspectorChange = useCallback(
    (patch: Partial<WorkflowNode>) => {
      if (!selectedNodeId) return;
      const current = wfNodesRef.current[selectedNodeId];
      if (!current) return;
      const next: WorkflowNode = { ...current, ...patch };
      wfNodesRef.current[selectedNodeId] = next;
      setRfNodes((nodes) =>
        nodes.map((n) =>
          n.id === selectedNodeId
            ? {
                ...n,
                data: {
                  ...n.data,
                  label: next.label ?? n.data.label,
                  toolName: next.type,
                  argsSummary: summarizeArgs(next.args),
                },
              }
            : n,
        ),
      );
    },
    [selectedNodeId, setRfNodes],
  );

  const onInspectorDelete = useCallback(
    (nodeId: string) => {
      delete wfNodesRef.current[nodeId];
      setRfNodes((nodes) => nodes.filter((n) => n.id !== nodeId));
      setRfEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      if (selectedNodeId === nodeId) setSelectedNodeId(null);
    },
    [selectedNodeId, setRfNodes, setRfEdges],
  );

  // -------------------------------------------------------------------------
  // Save / Run / Delete / Duplicate
  // -------------------------------------------------------------------------

  const buildWorkflowToSave = useCallback((): Workflow | null => {
    if (!workflow) return null;
    const nodes = Object.values(wfNodesRef.current);
    return {
      ...workflow,
      name,
      nodes,
    };
  }, [workflow, name]);

  const handleSave = useCallback(async (): Promise<void> => {
    const wf = buildWorkflowToSave();
    if (!wf) return;
    setBusy("save");
    try {
      const exists = workflowId !== "new"
        && await api.getWorkflow(wf.id).then(() => true).catch(() => false);
      if (!exists) {
        await api.saveWorkflow(wf);
        flashToast("ok", `Saved as ${wf.id}`);
      } else {
        await api.updateWorkflow(wf.id, {
          name: wf.name,
          nodes: wf.nodes,
          variables: wf.variables,
        });
        flashToast("ok", `Updated ${wf.id}`);
      }
      setWorkflow(wf);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      flashToast("err", `Save failed: ${msg}`);
    } finally {
      setBusy("idle");
    }
  }, [buildWorkflowToSave, workflowId, flashToast]);

  const handleRun = useCallback(async (): Promise<void> => {
    const wf = buildWorkflowToSave();
    if (!wf) return;
    setBusy("run");
    try {
      // Save first so the backend has a fresh copy to execute.
      const exists = await api.getWorkflow(wf.id).then(() => true).catch(() => false);
      if (exists) {
        await api.updateWorkflow(wf.id, { nodes: wf.nodes, name: wf.name });
      } else {
        await api.saveWorkflow(wf);
      }
      const result = await api.runWorkflow(wf.id);
      flashToast("ok", `Run started: ${result.run_id.slice(0, 8)}`);
      if (onRunLaunched) onRunLaunched(result.run_id, wf.id);
      if (onBackToList) onBackToList();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      flashToast("err", `Run failed: ${msg}`);
    } finally {
      setBusy("idle");
    }
  }, [buildWorkflowToSave, flashToast, onRunLaunched, onBackToList]);

  const handleDelete = useCallback(async (): Promise<void> => {
    if (!workflow || workflowId === "new") {
      flashToast("err", "Nothing to delete (unsaved workflow)");
      return;
    }
    if (!window.confirm(`Delete workflow '${workflow.name}'? This cannot be undone.`)) {
      return;
    }
    setBusy("delete");
    try {
      await api.deleteWorkflow(workflow.id);
      flashToast("ok", `Deleted ${workflow.id}`);
      if (onBackToList) onBackToList();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      flashToast("err", `Delete failed: ${msg}`);
    } finally {
      setBusy("idle");
    }
  }, [workflow, workflowId, flashToast, onBackToList]);

  const handleDuplicate = useCallback(async (): Promise<void> => {
    if (!workflow || workflowId === "new") {
      flashToast("err", "Save the workflow before duplicating");
      return;
    }
    setBusy("duplicate");
    try {
      const result = await api.duplicateWorkflow(workflow.id);
      flashToast("ok", `Duplicated to ${result.id}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      flashToast("err", `Duplicate failed: ${msg}`);
    } finally {
      setBusy("idle");
    }
  }, [workflow, workflowId, flashToast]);

  // -------------------------------------------------------------------------
  // Node types — memoized to avoid React Flow warnings
  // -------------------------------------------------------------------------

  const nodeTypes = useMemo(() => workflowNodeTypes, []);

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-zinc-500">
        <Loader2 className="animate-spin" /> <span className="ml-2">Loading workflow...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-red-400">
        <AlertTriangle className="mr-2" /> {error}
      </div>
    );
  }

  const selectedNode = selectedNodeId ? wfNodesRef.current[selectedNodeId] : null;

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Top toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800 bg-zinc-950">
        <button
          type="button"
          onClick={onBackToList}
          className="text-xs text-zinc-400 hover:text-zinc-200 px-2 py-1 rounded hover:bg-zinc-800"
        >
          Back
        </button>
        <span className="text-xs text-zinc-600">/</span>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="bg-transparent border-b border-transparent focus:border-zinc-600 px-1 py-0.5 text-sm font-medium text-zinc-100 focus:outline-none"
          placeholder="Workflow name"
        />
        <span className="text-[10px] text-zinc-500 font-mono ml-1">
          {workflow?.id ?? ""} v{workflow?.version ?? 1}
        </span>

        <div className="flex-1" />

        <button
          type="button"
          onClick={() => setLocked((l) => !l)}
          className="inline-flex items-center gap-1 text-xs text-zinc-300 hover:text-zinc-100 px-2 py-1 rounded hover:bg-zinc-800"
          title={locked ? "Unlock layout" : "Lock layout"}
        >
          {locked ? <Lock size={12} /> : <Unlock size={12} />}
          {locked ? "Locked" : "Editable"}
        </button>

        <button
          type="button"
          onClick={handleDuplicate}
          disabled={busy !== "idle"}
          className="inline-flex items-center gap-1 text-xs text-zinc-300 hover:text-zinc-100 px-2 py-1 rounded border border-zinc-700 hover:bg-zinc-800 disabled:opacity-50"
        >
          {busy === "duplicate" ? <Loader2 size={12} className="animate-spin" /> : <Copy size={12} />}
          Duplicate
        </button>

        <button
          type="button"
          onClick={handleDelete}
          disabled={busy !== "idle"}
          className="inline-flex items-center gap-1 text-xs text-red-300 hover:text-red-100 px-2 py-1 rounded border border-red-900 hover:bg-red-950/50 disabled:opacity-50"
        >
          {busy === "delete" ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
          Delete
        </button>

        <button
          type="button"
          onClick={handleRun}
          disabled={busy !== "idle"}
          className="inline-flex items-center gap-1 text-xs text-emerald-200 px-2 py-1 rounded bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50"
        >
          {busy === "run" ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
          Run
        </button>

        <button
          type="button"
          onClick={handleSave}
          disabled={busy !== "idle"}
          className="inline-flex items-center gap-1 text-xs text-blue-200 px-2 py-1 rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-50"
        >
          {busy === "save" ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
          Save
        </button>
      </div>

      {/* 3-pane layout: palette | canvas | inspector */}
      <div className="flex-1 flex overflow-hidden">
        <NodePalette />

        <div
          className="flex-1 relative"
          onDrop={onDrop}
          onDragOver={onDragOver}
        >
          <ReactFlow
            nodes={rfNodes}
            edges={rfEdges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChangeWrapped}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onSelectionChange={onSelectionChange}
            nodesDraggable={!locked}
            nodesConnectable={!locked}
            elementsSelectable={!locked}
            connectionLineType={ConnectionLineType.Bezier}
            fitView
            minZoom={0.2}
            maxZoom={2}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#27272a" />
            <MiniMap
              nodeStrokeColor="#3f3f46"
              nodeColor={(n) => {
                const vt = (n.data as WorkflowNodeData | undefined)?.visualType;
                switch (vt) {
                  case "start": return "#10b981";
                  case "end": return "#ef4444";
                  case "condition": return "#eab308";
                  case "loop": return "#a855f7";
                  case "notification": return "#f97316";
                  case "ai_decision": return "#8b5cf6";
                  default: return "#3b82f6";
                }
              }}
            />
            <Controls showInteractive={!locked} />
          </ReactFlow>

          {/* Empty-state overlay */}
          {rfNodes.length === 0 && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="text-center text-zinc-500">
                <p className="text-sm">Drag a node from the left to get started.</p>
                <p className="text-[11px] mt-1">
                  Tip: hold and drag from a node&apos;s bottom handle to another
                  node&apos;s top handle to connect them.
                </p>
              </div>
            </div>
          )}

          {/* Toast */}
          {toast && (
            <div
              className={[
                "absolute bottom-3 left-3 px-3 py-1.5 rounded text-xs font-medium shadow-lg",
                toast.kind === "ok"
                  ? "bg-emerald-900/90 text-emerald-100 border border-emerald-700"
                  : "bg-red-900/90 text-red-100 border border-red-700",
              ].join(" ")}
            >
              {toast.kind === "ok" ? <Check size={12} className="inline mr-1" /> : <AlertTriangle size={12} className="inline mr-1" />}
              {toast.msg}
            </div>
          )}
        </div>

        <NodeInspector
          node={selectedNode}
          onChange={onInspectorChange}
          onDelete={onInspectorDelete}
        />
      </div>
    </div>
  );
}
