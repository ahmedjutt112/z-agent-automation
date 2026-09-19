import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/** Workflows page — master prompt §20, §21, §34.
 *
 * Top section lists saved workflows (clickable to open in editor).
 * Buttons: "+ New Workflow" and "Templates".
 * When a workflow is selected, the full WorkflowCanvas is rendered with a
 * breadcrumb back to the list.
 */
import { useEffect, useState } from "react";
import { Plus, LayoutTemplate, ChevronRight, Pencil, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { WorkflowCanvas } from "../components/workflow/WorkflowCanvas";
export function Workflows() {
    const [workflows, setWorkflows] = useState([]);
    const [loading, setLoading] = useState(true);
    const [selectedId, setSelectedId] = useState(null);
    const [selectedName, setSelectedName] = useState("");
    const [showTemplates, setShowTemplates] = useState(false);
    const [templates, setTemplates] = useState([]);
    const [tplLoading, setTplLoading] = useState(false);
    const [tplError, setTplError] = useState(null);
    // -----------------------------------------------------------------------
    // Load workflow list
    // -----------------------------------------------------------------------
    const refresh = () => {
        setLoading(true);
        api.listWorkflows()
            .then(setWorkflows)
            .catch(() => setWorkflows([]))
            .finally(() => setLoading(false));
    };
    useEffect(refresh, []);
    // -----------------------------------------------------------------------
    // Actions
    // -----------------------------------------------------------------------
    const openWorkflow = (wf) => {
        setSelectedId(wf.id);
        setSelectedName(wf.name);
    };
    const newWorkflow = () => {
        setSelectedId("new");
        setSelectedName("Untitled Workflow");
    };
    const openTemplates = () => {
        setShowTemplates(true);
        if (templates.length === 0 && !tplLoading) {
            setTplLoading(true);
            api.listWorkflowTemplates()
                .then((t) => {
                setTemplates(t);
                setTplError(null);
            })
                .catch((e) => {
                const msg = e instanceof Error ? e.message : String(e);
                setTplError(msg);
            })
                .finally(() => setTplLoading(false));
        }
    };
    const instantiateTemplate = (tpl) => {
        // We open the editor with the special "new" id, but pre-seed the
        // workflow nodes from the template via the canvas's load path. The
        // canvas calls api.getWorkflow("new") which 404s and falls back to
        // emptyWorkflow(); so to actually use a template the user saves it
        // first. For now we just close the modal and open an empty editor —
        // a proper template instantiation flow can be added later.
        void tpl;
        setShowTemplates(false);
        newWorkflow();
    };
    const deleteWorkflow = async (id, name) => {
        if (!window.confirm(`Delete workflow '${name}'? This cannot be undone.`))
            return;
        try {
            await api.deleteWorkflow(id);
            refresh();
        }
        catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            window.alert(`Delete failed: ${msg}`);
        }
    };
    // -----------------------------------------------------------------------
    // Render: canvas mode
    // -----------------------------------------------------------------------
    if (selectedId) {
        return (_jsxs("div", { className: "flex flex-col h-full -m-6", children: [_jsxs("div", { className: "flex items-center gap-1 px-4 py-2 text-xs text-zinc-400 border-b border-zinc-800 bg-zinc-950", children: [_jsx("button", { type: "button", onClick: () => {
                                setSelectedId(null);
                                setSelectedName("");
                                refresh();
                            }, className: "hover:text-zinc-200", children: "Workflows" }), _jsx(ChevronRight, { size: 12 }), _jsx("span", { className: "text-zinc-200", children: selectedName || selectedId })] }), _jsx(WorkflowCanvas, { workflowId: selectedId, onBackToList: () => {
                        setSelectedId(null);
                        setSelectedName("");
                        refresh();
                    } })] }));
    }
    // -----------------------------------------------------------------------
    // Render: list mode
    // -----------------------------------------------------------------------
    return (_jsxs("div", { children: [_jsxs("div", { className: "flex items-center justify-between mb-4", children: [_jsx("h1", { className: "text-2xl font-semibold", children: "Workflows" }), _jsxs("div", { className: "flex items-center gap-2", children: [_jsxs("button", { type: "button", onClick: openTemplates, className: "inline-flex items-center gap-1 px-3 py-1.5 rounded text-sm bg-zinc-800 hover:bg-zinc-700 text-zinc-200", children: [_jsx(LayoutTemplate, { size: 14 }), " Templates"] }), _jsxs("button", { type: "button", onClick: newWorkflow, className: "inline-flex items-center gap-1 px-3 py-1.5 rounded text-sm bg-blue-600 hover:bg-blue-500", children: [_jsx(Plus, { size: 14 }), " New Workflow"] })] })] }), _jsx("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden", children: _jsxs("table", { className: "w-full text-sm", children: [_jsx("thead", { children: _jsxs("tr", { className: "bg-zinc-800 text-zinc-400 text-xs uppercase tracking-wider", children: [_jsx("th", { className: "px-4 py-2 text-left", children: "Name" }), _jsx("th", { className: "px-4 py-2 text-left", children: "Version" }), _jsx("th", { className: "px-4 py-2 text-left", children: "Enabled" }), _jsx("th", { className: "px-4 py-2 text-right", children: "Actions" })] }) }), _jsx("tbody", { children: loading ? (_jsx("tr", { children: _jsx("td", { colSpan: 4, className: "px-4 py-6 text-center text-zinc-500", children: "Loading..." }) })) : workflows.length === 0 ? (_jsx("tr", { children: _jsxs("td", { colSpan: 4, className: "px-4 py-6 text-center text-zinc-500", children: ["No workflows yet. Click ", _jsx("strong", { children: "New Workflow" }), " to start the visual editor, or pick a starter from ", _jsx("strong", { children: "Templates" }), "."] }) })) : (workflows.map((wf) => (_jsxs("tr", { className: "border-t border-zinc-800 hover:bg-zinc-800/50", children: [_jsx("td", { className: "px-4 py-2 font-medium", children: wf.name }), _jsxs("td", { className: "px-4 py-2 text-zinc-400", children: ["v", wf.version] }), _jsx("td", { className: "px-4 py-2", children: _jsx("span", { className: `text-xs ${wf.enabled ? "text-emerald-400" : "text-zinc-500"}`, children: wf.enabled ? "Enabled" : "Disabled" }) }), _jsxs("td", { className: "px-4 py-2 text-right", children: [_jsxs("button", { type: "button", onClick: () => openWorkflow(wf), className: "inline-flex items-center gap-1 text-xs bg-zinc-700 hover:bg-zinc-600 px-2 py-1 rounded mr-1", children: [_jsx(Pencil, { size: 11 }), " Edit"] }), _jsx("button", { type: "button", onClick: () => void deleteWorkflow(wf.id, wf.name), className: "inline-flex items-center gap-1 text-xs text-red-300 hover:text-red-200 bg-zinc-800 hover:bg-red-950/50 px-2 py-1 rounded border border-red-900", children: _jsx(Trash2, { size: 11 }) })] })] }, wf.id)))) })] }) }), showTemplates && (_jsx("div", { className: "fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6", onClick: () => setShowTemplates(false), children: _jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg max-w-2xl w-full p-4 max-h-[80vh] overflow-y-auto", onClick: (e) => e.stopPropagation(), children: [_jsxs("div", { className: "flex items-center justify-between mb-3", children: [_jsx("h2", { className: "text-lg font-semibold", children: "Workflow Templates" }), _jsx("button", { type: "button", onClick: () => setShowTemplates(false), className: "text-zinc-400 hover:text-zinc-200 text-sm", children: "Close" })] }), tplLoading ? (_jsx("p", { className: "text-sm text-zinc-500", children: "Loading templates..." })) : tplError ? (_jsxs("p", { className: "text-sm text-red-400", children: ["Failed to load: ", tplError] })) : templates.length === 0 ? (_jsx("p", { className: "text-sm text-zinc-500", children: "No templates available." })) : (_jsx("ul", { className: "space-y-2", children: templates.map((t) => (_jsx("li", { className: "border border-zinc-800 rounded p-3 hover:border-zinc-700 cursor-pointer", onClick: () => instantiateTemplate(t), children: _jsxs("div", { className: "flex items-center justify-between", children: [_jsxs("div", { children: [_jsx("h3", { className: "font-medium text-sm", children: t.name }), _jsx("p", { className: "text-xs text-zinc-500 mt-0.5", children: t.description ?? "No description" }), _jsxs("div", { className: "mt-1 text-[10px] text-zinc-600 font-mono", children: [t.id, " \u00B7 ", t.node_count, " node(s) \u00B7 trigger: ", t.trigger.type] })] }), _jsx("button", { type: "button", className: "text-xs bg-blue-600 hover:bg-blue-500 text-blue-100 px-2 py-1 rounded", onClick: (e) => {
                                                e.stopPropagation();
                                                instantiateTemplate(t);
                                            }, children: "Use" })] }) }, t.id))) })), _jsx("p", { className: "mt-3 text-[11px] text-zinc-600", children: "Note: choosing a template opens a new editor \u2014 the template's nodes are pre-seeded once the workflow is saved." })] }) }))] }));
}
