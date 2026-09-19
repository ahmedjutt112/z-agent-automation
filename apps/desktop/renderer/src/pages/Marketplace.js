import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * Marketplace page — master prompt §52 (template marketplace) + §51 (import).
 *
 * UI layout:
 *  - Header: title + search bar + category filter dropdown.
 *  - Left sidebar: 10 categories with counts (click to filter).
 *  - Featured section: 6 cards (the featured templates).
 *  - Template grid: cards with name / description / tags / author / version
 *    / downloads / rating + an "Install" button.
 *  - Click a card → opens a detail modal with full description, workflow
 *    preview, required permissions (risk-level color-coded), and an Install
 *    button that calls POST /marketplace/install/{id} and then navigates
 *    to the workflow editor.
 *  - Submit form: user can submit their own workflow (name, description,
 *    category, tags, workflow JSON).
 *
 * CRITICAL — master prompt §52 + §51:
 *  - Imported workflows MUST be sandboxed + permission-scanned.
 *  - Imported workflows NEVER auto-execute (enabled=False on install).
 *  - Show permission requirements BEFORE the user enables a workflow.
 *  - The install modal surfaces a warning notice about the sandboxing.
 */
import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";
// ---------------------------------------------------------------------------
// Risk-level color coding (master prompt §9).
// ---------------------------------------------------------------------------
const RISK_COLORS = {
    low: "text-emerald-400 border-emerald-500/40 bg-emerald-500/10",
    medium: "text-amber-400 border-amber-500/40 bg-amber-500/10",
    high: "text-orange-400 border-orange-500/40 bg-orange-500/10",
    critical: "text-red-400 border-red-500/40 bg-red-500/10",
};
function RiskBadge({ level }) {
    return (_jsx("span", { className: `px-2 py-0.5 text-xs rounded border ${RISK_COLORS[level]}`, title: `Risk level: ${level}`, children: level.toUpperCase() }));
}
// Star rating renderer (1-5).
function Stars({ value, count }) {
    const full = Math.round(value);
    return (_jsxs("span", { className: "text-amber-400 text-xs", title: `${value} / 5${count ? ` (${count} ratings)` : ""}`, children: ["★".repeat(full), "☆".repeat(Math.max(0, 5 - full)), count !== undefined && (_jsxs("span", { className: "text-zinc-500 ml-1", children: ["(", count, ")"] }))] }));
}
// ---------------------------------------------------------------------------
// Main page component.
// ---------------------------------------------------------------------------
export function Marketplace() {
    const setView = useStore((s) => s.setView);
    const [templates, setTemplates] = useState([]);
    const [categories, setCategories] = useState([]);
    const [featured, setFeatured] = useState([]);
    const [selectedCategory, setSelectedCategory] = useState(null);
    const [searchQuery, setSearchQuery] = useState("");
    const [activeTemplate, setActiveTemplate] = useState(null);
    const [installing, setInstalling] = useState(false);
    const [installError, setInstallError] = useState(null);
    const [showSubmitForm, setShowSubmitForm] = useState(false);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    // ---- Initial load: featured + categories + all templates ----
    useEffect(() => {
        let cancelled = false;
        (async () => {
            setLoading(true);
            setError(null);
            try {
                const [feat, cats, all] = await Promise.all([
                    api.marketplace.getFeatured(),
                    api.marketplace.listCategories(),
                    api.marketplace.listTemplates(),
                ]);
                if (cancelled)
                    return;
                setFeatured(feat);
                setCategories(cats.categories);
                setTemplates(all);
            }
            catch (exc) {
                if (!cancelled) {
                    setError(`Failed to load marketplace: ${exc}`);
                }
            }
            finally {
                if (!cancelled)
                    setLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);
    // ---- Filtered templates (search + category) ----
    const visibleTemplates = useMemo(() => {
        let list = templates;
        if (selectedCategory) {
            list = list.filter((t) => t.category === selectedCategory);
        }
        if (searchQuery.trim()) {
            const q = searchQuery.trim().toLowerCase();
            list = list.filter((t) => t.name.toLowerCase().includes(q) ||
                (t.description || "").toLowerCase().includes(q) ||
                t.tags.some((tag) => tag.toLowerCase().includes(q)));
        }
        return list;
    }, [templates, selectedCategory, searchQuery]);
    // ---- Search handler (debounced via explicit button or Enter) ----
    async function handleSearch() {
        if (!searchQuery.trim()) {
            // Empty search → reload all templates.
            const all = await api.marketplace.listTemplates();
            setTemplates(all);
            return;
        }
        try {
            const results = await api.marketplace.searchTemplates(searchQuery);
            setTemplates(results);
            setSelectedCategory(null);
        }
        catch (exc) {
            setError(`Search failed: ${exc}`);
        }
    }
    // ---- Install handler — master prompt §52 ----
    async function handleInstall(template) {
        setInstalling(true);
        setInstallError(null);
        try {
            const result = await api.marketplace.installTemplate(template.id);
            // The installed workflow is saved with enabled=false (master prompt §51).
            // Surface a success notice and offer to open the workflow editor.
            setActiveTemplate(null);
            // Navigate to the workflows view so the user can review + enable.
            setView("workflows");
            void result;
        }
        catch (exc) {
            setInstallError(`Install failed: ${exc}`);
        }
        finally {
            setInstalling(false);
        }
    }
    return (_jsxs("div", { className: "space-y-6", children: [_jsxs("div", { className: "flex items-center justify-between gap-4", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-2xl font-semibold", children: "Workflow Marketplace" }), _jsx("p", { className: "text-sm text-zinc-500 mt-1", children: "Browse, install, and submit workflow templates across 10 categories. Imported workflows are sandboxed and permission-scanned (sections 51 + 52)." })] }), _jsx("button", { onClick: () => setShowSubmitForm((v) => !v), className: "px-3 py-1.5 text-sm rounded bg-zinc-800 hover:bg-zinc-700 border border-zinc-700", children: showSubmitForm ? "Cancel" : "Submit Template" })] }), _jsxs("div", { className: "flex gap-2", children: [_jsx("input", { type: "text", value: searchQuery, onChange: (e) => setSearchQuery(e.target.value), onKeyDown: (e) => {
                            if (e.key === "Enter")
                                handleSearch();
                        }, placeholder: "Search by name, description, or tag...", className: "flex-1 px-3 py-2 rounded bg-zinc-900 border border-zinc-800 text-sm placeholder-zinc-600" }), _jsx("button", { onClick: handleSearch, className: "px-4 py-2 text-sm rounded bg-blue-600 hover:bg-blue-500", children: "Search" }), _jsxs("select", { value: selectedCategory || "", onChange: (e) => setSelectedCategory(e.target.value || null), className: "px-3 py-2 rounded bg-zinc-900 border border-zinc-800 text-sm", children: [_jsx("option", { value: "", children: "All categories" }), categories.map((c) => (_jsxs("option", { value: c.category, children: [c.label, " (", c.count, ")"] }, c.category)))] })] }), error && (_jsx("div", { className: "px-3 py-2 rounded border border-red-500/40 bg-red-500/10 text-red-400 text-sm", children: error })), showSubmitForm && (_jsx(SubmitForm, { categories: categories, onSubmitted: async () => {
                    setShowSubmitForm(false);
                    // Reload templates + categories to reflect the new submission.
                    const [all, cats] = await Promise.all([
                        api.marketplace.listTemplates(),
                        api.marketplace.listCategories(),
                    ]);
                    setTemplates(all);
                    setCategories(cats.categories);
                } })), featured.length > 0 && !selectedCategory && !searchQuery && (_jsxs("section", { children: [_jsx("h2", { className: "text-sm uppercase tracking-wider text-zinc-500 mb-3", children: "Featured" }), _jsx("div", { className: "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3", children: featured.map((tpl) => (_jsx(TemplateCard, { template: tpl, onClick: () => setActiveTemplate(tpl), onInstall: () => handleInstall(tpl) }, tpl.id))) })] })), _jsxs("section", { children: [_jsx("h2", { className: "text-sm uppercase tracking-wider text-zinc-500 mb-3", children: selectedCategory
                            ? `${categories.find((c) => c.category === selectedCategory)?.label || selectedCategory} (${visibleTemplates.length})`
                            : `All Templates (${visibleTemplates.length})` }), loading ? (_jsx("div", { className: "text-sm text-zinc-500", children: "Loading templates..." })) : visibleTemplates.length === 0 ? (_jsx("div", { className: "text-sm text-zinc-500", children: "No templates match your filters." })) : (_jsx("div", { className: "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3", children: visibleTemplates.map((tpl) => (_jsx(TemplateCard, { template: tpl, onClick: () => setActiveTemplate(tpl), onInstall: () => handleInstall(tpl) }, tpl.id))) }))] }), activeTemplate && (_jsx(TemplateDetailModal, { template: activeTemplate, installing: installing, installError: installError, onClose: () => setActiveTemplate(null), onInstall: () => handleInstall(activeTemplate) }))] }));
}
function TemplateCard({ template, onClick, onInstall }) {
    return (_jsxs("div", { className: "p-4 rounded border border-zinc-800 bg-zinc-900 hover:border-zinc-700 cursor-pointer transition-colors", onClick: onClick, children: [_jsxs("div", { className: "flex items-start justify-between gap-2", children: [_jsxs("div", { className: "min-w-0 flex-1", children: [_jsx("div", { className: "text-sm font-medium truncate", children: template.name }), _jsxs("div", { className: "text-xs text-zinc-500 mt-0.5", children: ["by ", template.author] })] }), _jsx(RiskBadge, { level: template.risk_level })] }), _jsx("p", { className: "text-xs text-zinc-400 mt-2 line-clamp-2", children: template.description }), _jsx("div", { className: "flex flex-wrap gap-1 mt-2", children: template.tags.slice(0, 4).map((tag) => (_jsx("span", { className: "px-1.5 py-0.5 text-[10px] rounded bg-zinc-800 text-zinc-400", children: tag }, tag))) }), _jsxs("div", { className: "flex items-center justify-between mt-3 text-xs text-zinc-500", children: [_jsx(Stars, { value: template.rating, count: template.rating_count }), _jsxs("span", { children: ["v", template.version, " \u00B7 ", template.downloads_count, " downloads"] })] }), _jsx("button", { onClick: (e) => {
                    e.stopPropagation();
                    onInstall();
                }, className: "w-full mt-3 px-3 py-1.5 text-xs rounded bg-blue-600 hover:bg-blue-500", children: "Install" })] }));
}
function TemplateDetailModal({ template, installing, installError, onClose, onInstall, }) {
    return (_jsx("div", { className: "fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4", onClick: onClose, children: _jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded max-w-3xl w-full max-h-[90vh] overflow-y-auto", onClick: (e) => e.stopPropagation(), children: [_jsxs("div", { className: "flex items-start justify-between p-4 border-b border-zinc-800", children: [_jsxs("div", { children: [_jsx("h2", { className: "text-lg font-semibold", children: template.name }), _jsxs("div", { className: "text-xs text-zinc-500 mt-1", children: ["by ", template.author, " \u00B7 v", template.version, " \u00B7 ", template.downloads_count, " downloads"] })] }), _jsxs("div", { className: "flex items-center gap-2", children: [_jsx(RiskBadge, { level: template.risk_level }), _jsx("button", { onClick: onClose, className: "px-2 py-1 text-xs rounded hover:bg-zinc-800", children: "Close" })] })] }), _jsxs("div", { className: "p-4 space-y-4", children: [_jsxs("div", { className: "px-3 py-2 rounded border border-amber-500/40 bg-amber-500/10 text-amber-400 text-xs", children: ["Imported workflows must be sandboxed and permission-scanned (master prompt \u00A752). This workflow will be installed with", " ", _jsx("span", { className: "font-mono", children: "enabled=false" }), " \u2014 you must manually review and enable it before any node can run."] }), _jsxs("div", { children: [_jsx("div", { className: "text-xs uppercase tracking-wider text-zinc-500 mb-1", children: "Description" }), _jsx("p", { className: "text-sm text-zinc-300", children: template.description })] }), template.tags.length > 0 && (_jsxs("div", { children: [_jsx("div", { className: "text-xs uppercase tracking-wider text-zinc-500 mb-1", children: "Tags" }), _jsx("div", { className: "flex flex-wrap gap-1", children: template.tags.map((tag) => (_jsx("span", { className: "px-2 py-0.5 text-xs rounded bg-zinc-800 text-zinc-400", children: tag }, tag))) })] })), _jsxs("div", { children: [_jsxs("div", { className: "text-xs uppercase tracking-wider text-zinc-500 mb-1", children: ["Required Permissions (", template.permissions_required.length, ")"] }), template.permissions_required.length === 0 ? (_jsx("div", { className: "text-xs text-zinc-500", children: "No tool-level permissions required." })) : (_jsx("ul", { className: "grid grid-cols-2 gap-1 text-xs", children: template.permissions_required.map((perm) => (_jsx("li", { className: "px-2 py-1 rounded bg-zinc-800 text-zinc-300 font-mono", children: perm }, perm))) }))] }), _jsxs("div", { children: [_jsxs("div", { className: "text-xs uppercase tracking-wider text-zinc-500 mb-1", children: ["Workflow Preview (", template.workflow.nodes.length, " nodes)"] }), _jsx("ol", { className: "space-y-1 text-xs", children: template.workflow.nodes.map((node, idx) => (_jsxs("li", { className: "px-2 py-1 rounded bg-zinc-950 border border-zinc-800", children: [_jsxs("span", { className: "text-zinc-500 mr-2", children: [idx + 1, "."] }), _jsx("span", { className: "font-mono text-zinc-300", children: node.type }), _jsxs("span", { className: "text-zinc-600 ml-2", children: ["#", node.id] })] }, node.id))) })] }), installError && (_jsx("div", { className: "px-3 py-2 rounded border border-red-500/40 bg-red-500/10 text-red-400 text-xs", children: installError }))] }), _jsxs("div", { className: "p-4 border-t border-zinc-800 flex justify-end gap-2", children: [_jsx("button", { onClick: onClose, className: "px-3 py-1.5 text-sm rounded hover:bg-zinc-800", children: "Cancel" }), _jsx("button", { onClick: onInstall, disabled: installing, className: "px-3 py-1.5 text-sm rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50", children: installing ? "Installing..." : "Install Workflow" })] })] }) }));
}
function SubmitForm({ categories, onSubmitted }) {
    const [name, setName] = useState("");
    const [description, setDescription] = useState("");
    const [category, setCategory] = useState(categories[0]?.category || "");
    const [tagsInput, setTagsInput] = useState("");
    const [workflowJson, setWorkflowJson] = useState("");
    const [author, setAuthor] = useState("");
    const [error, setError] = useState(null);
    const [submitting, setSubmitting] = useState(false);
    async function handleSubmit() {
        setError(null);
        if (!name.trim() || !workflowJson.trim() || !category) {
            setError("Name, category, and workflow JSON are required.");
            return;
        }
        let workflow;
        try {
            workflow = JSON.parse(workflowJson);
        }
        catch (exc) {
            setError(`Invalid workflow JSON: ${exc}`);
            return;
        }
        setSubmitting(true);
        try {
            await api.marketplace.submitTemplate({
                workflow,
                author: author || "anonymous",
                category,
                tags: tagsInput
                    .split(",")
                    .map((t) => t.trim())
                    .filter(Boolean),
            });
            setName("");
            setDescription("");
            setTagsInput("");
            setWorkflowJson("");
            onSubmitted();
        }
        catch (exc) {
            setError(`Submit failed: ${exc}`);
        }
        finally {
            setSubmitting(false);
        }
    }
    return (_jsxs("div", { className: "p-4 rounded border border-zinc-800 bg-zinc-900 space-y-3", children: [_jsx("div", { className: "text-sm font-medium", children: "Submit a new template" }), _jsxs("div", { className: "grid grid-cols-2 gap-3", children: [_jsxs("label", { className: "text-xs text-zinc-500", children: ["Name", _jsx("input", { type: "text", value: name, onChange: (e) => setName(e.target.value), className: "mt-1 w-full px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-sm" })] }), _jsxs("label", { className: "text-xs text-zinc-500", children: ["Author", _jsx("input", { type: "text", value: author, onChange: (e) => setAuthor(e.target.value), placeholder: "anonymous", className: "mt-1 w-full px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-sm" })] }), _jsxs("label", { className: "text-xs text-zinc-500", children: ["Category", _jsx("select", { value: category, onChange: (e) => setCategory(e.target.value), className: "mt-1 w-full px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-sm", children: categories.map((c) => (_jsx("option", { value: c.category, children: c.label }, c.category))) })] }), _jsxs("label", { className: "text-xs text-zinc-500", children: ["Tags (comma-separated)", _jsx("input", { type: "text", value: tagsInput, onChange: (e) => setTagsInput(e.target.value), placeholder: "tag1, tag2", className: "mt-1 w-full px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-sm" })] })] }), _jsxs("label", { className: "block text-xs text-zinc-500", children: ["Description", _jsx("textarea", { value: description, onChange: (e) => setDescription(e.target.value), rows: 2, className: "mt-1 w-full px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-sm" })] }), _jsxs("label", { className: "block text-xs text-zinc-500", children: ["Workflow JSON (paste the full Workflow object)", _jsx("textarea", { value: workflowJson, onChange: (e) => setWorkflowJson(e.target.value), rows: 6, placeholder: '{"id": "...", "name": "...", "nodes": [...], "trigger": {...}}', className: "mt-1 w-full px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-sm font-mono" })] }), error && (_jsx("div", { className: "text-xs text-red-400 px-2 py-1 rounded bg-red-500/10 border border-red-500/40", children: error })), _jsx("div", { className: "flex justify-end gap-2", children: _jsx("button", { onClick: handleSubmit, disabled: submitting, className: "px-3 py-1.5 text-sm rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50", children: submitting ? "Submitting..." : "Submit Template" }) })] }));
}
