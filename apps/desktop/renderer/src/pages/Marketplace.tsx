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

import React, { useEffect, useMemo, useState } from "react";
import { api, Workflow, RiskLevel } from "../lib/api";
import { useStore } from "../store";

// ---------------------------------------------------------------------------
// Types — mirror what the backend returns.
// ---------------------------------------------------------------------------

export interface MarketplaceCategory {
  category: string;
  label: string;
  count: number;
}

export interface MarketplaceTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  author: string;
  version: string;
  downloads_count: number;
  rating: number;
  rating_count: number;
  workflow: Workflow;
  tags: string[];
  created_at: string;
  updated_at: string;
  permissions_required: string[];
  risk_level: RiskLevel;
  featured: boolean;
}

export interface InstallResponse {
  workflow: Workflow;
  permissions_required: string[];
  risk_level: RiskLevel;
  warnings: string[];
  template_id: string;
  installed: boolean;
}

// ---------------------------------------------------------------------------
// Risk-level color coding (master prompt §9).
// ---------------------------------------------------------------------------

const RISK_COLORS: Record<RiskLevel, string> = {
  low: "text-emerald-400 border-emerald-500/40 bg-emerald-500/10",
  medium: "text-amber-400 border-amber-500/40 bg-amber-500/10",
  high: "text-orange-400 border-orange-500/40 bg-orange-500/10",
  critical: "text-red-400 border-red-500/40 bg-red-500/10",
};

function RiskBadge({ level }: { level: RiskLevel }) {
  return (
    <span
      className={`px-2 py-0.5 text-xs rounded border ${RISK_COLORS[level]}`}
      title={`Risk level: ${level}`}
    >
      {level.toUpperCase()}
    </span>
  );
}

// Star rating renderer (1-5).
function Stars({ value, count }: { value: number; count?: number }) {
  const full = Math.round(value);
  return (
    <span className="text-amber-400 text-xs" title={`${value} / 5${count ? ` (${count} ratings)` : ""}`}>
      {"★".repeat(full)}
      {"☆".repeat(Math.max(0, 5 - full))}
      {count !== undefined && (
        <span className="text-zinc-500 ml-1">({count})</span>
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main page component.
// ---------------------------------------------------------------------------

export function Marketplace() {
  const setView = useStore((s) => s.setView);
  const [templates, setTemplates] = useState<MarketplaceTemplate[]>([]);
  const [categories, setCategories] = useState<MarketplaceCategory[]>([]);
  const [featured, setFeatured] = useState<MarketplaceTemplate[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [activeTemplate, setActiveTemplate] = useState<MarketplaceTemplate | null>(null);
  const [installing, setInstalling] = useState<boolean>(false);
  const [installError, setInstallError] = useState<string | null>(null);
  const [showSubmitForm, setShowSubmitForm] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

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
        if (cancelled) return;
        setFeatured(feat);
        setCategories(cats.categories);
        setTemplates(all);
      } catch (exc) {
        if (!cancelled) {
          setError(`Failed to load marketplace: ${exc}`);
        }
      } finally {
        if (!cancelled) setLoading(false);
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
      list = list.filter(
        (t) =>
          t.name.toLowerCase().includes(q) ||
          (t.description || "").toLowerCase().includes(q) ||
          t.tags.some((tag) => tag.toLowerCase().includes(q)),
      );
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
    } catch (exc) {
      setError(`Search failed: ${exc}`);
    }
  }

  // ---- Install handler — master prompt §52 ----
  async function handleInstall(template: MarketplaceTemplate) {
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
    } catch (exc) {
      setInstallError(`Install failed: ${exc}`);
    } finally {
      setInstalling(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Workflow Marketplace</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Browse, install, and submit workflow templates across 10 categories.
            Imported workflows are sandboxed and permission-scanned (sections 51 + 52).
          </p>
        </div>
        <button
          onClick={() => setShowSubmitForm((v) => !v)}
          className="px-3 py-1.5 text-sm rounded bg-zinc-800 hover:bg-zinc-700 border border-zinc-700"
        >
          {showSubmitForm ? "Cancel" : "Submit Template"}
        </button>
      </div>

      {/* Search bar */}
      <div className="flex gap-2">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSearch();
          }}
          placeholder="Search by name, description, or tag..."
          className="flex-1 px-3 py-2 rounded bg-zinc-900 border border-zinc-800 text-sm placeholder-zinc-600"
        />
        <button
          onClick={handleSearch}
          className="px-4 py-2 text-sm rounded bg-blue-600 hover:bg-blue-500"
        >
          Search
        </button>
        <select
          value={selectedCategory || ""}
          onChange={(e) => setSelectedCategory(e.target.value || null)}
          className="px-3 py-2 rounded bg-zinc-900 border border-zinc-800 text-sm"
        >
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c.category} value={c.category}>
              {c.label} ({c.count})
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div className="px-3 py-2 rounded border border-red-500/40 bg-red-500/10 text-red-400 text-sm">
          {error}
        </div>
      )}

      {showSubmitForm && (
        <SubmitForm
          categories={categories}
          onSubmitted={async () => {
            setShowSubmitForm(false);
            // Reload templates + categories to reflect the new submission.
            const [all, cats] = await Promise.all([
              api.marketplace.listTemplates(),
              api.marketplace.listCategories(),
            ]);
            setTemplates(all);
            setCategories(cats.categories);
          }}
        />
      )}

      {/* Featured section */}
      {featured.length > 0 && !selectedCategory && !searchQuery && (
        <section>
          <h2 className="text-sm uppercase tracking-wider text-zinc-500 mb-3">
            Featured
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {featured.map((tpl) => (
              <TemplateCard
                key={tpl.id}
                template={tpl}
                onClick={() => setActiveTemplate(tpl)}
                onInstall={() => handleInstall(tpl)}
              />
            ))}
          </div>
        </section>
      )}

      {/* All templates (filtered) */}
      <section>
        <h2 className="text-sm uppercase tracking-wider text-zinc-500 mb-3">
          {selectedCategory
            ? `${categories.find((c) => c.category === selectedCategory)?.label || selectedCategory} (${visibleTemplates.length})`
            : `All Templates (${visibleTemplates.length})`}
        </h2>
        {loading ? (
          <div className="text-sm text-zinc-500">Loading templates...</div>
        ) : visibleTemplates.length === 0 ? (
          <div className="text-sm text-zinc-500">
            No templates match your filters.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {visibleTemplates.map((tpl) => (
              <TemplateCard
                key={tpl.id}
                template={tpl}
                onClick={() => setActiveTemplate(tpl)}
                onInstall={() => handleInstall(tpl)}
              />
            ))}
          </div>
        )}
      </section>

      {/* Detail modal */}
      {activeTemplate && (
        <TemplateDetailModal
          template={activeTemplate}
          installing={installing}
          installError={installError}
          onClose={() => setActiveTemplate(null)}
          onInstall={() => handleInstall(activeTemplate)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TemplateCard
// ---------------------------------------------------------------------------

interface TemplateCardProps {
  template: MarketplaceTemplate;
  onClick: () => void;
  onInstall: () => void;
}

function TemplateCard({ template, onClick, onInstall }: TemplateCardProps) {
  return (
    <div
      className="p-4 rounded border border-zinc-800 bg-zinc-900 hover:border-zinc-700 cursor-pointer transition-colors"
      onClick={onClick}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium truncate">{template.name}</div>
          <div className="text-xs text-zinc-500 mt-0.5">by {template.author}</div>
        </div>
        <RiskBadge level={template.risk_level} />
      </div>
      <p className="text-xs text-zinc-400 mt-2 line-clamp-2">{template.description}</p>
      <div className="flex flex-wrap gap-1 mt-2">
        {template.tags.slice(0, 4).map((tag) => (
          <span
            key={tag}
            className="px-1.5 py-0.5 text-[10px] rounded bg-zinc-800 text-zinc-400"
          >
            {tag}
          </span>
        ))}
      </div>
      <div className="flex items-center justify-between mt-3 text-xs text-zinc-500">
        <Stars value={template.rating} count={template.rating_count} />
        <span>v{template.version} · {template.downloads_count} downloads</span>
      </div>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onInstall();
        }}
        className="w-full mt-3 px-3 py-1.5 text-xs rounded bg-blue-600 hover:bg-blue-500"
      >
        Install
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TemplateDetailModal
// ---------------------------------------------------------------------------

interface TemplateDetailModalProps {
  template: MarketplaceTemplate;
  installing: boolean;
  installError: string | null;
  onClose: () => void;
  onInstall: () => void;
}

function TemplateDetailModal({
  template,
  installing,
  installError,
  onClose,
  onInstall,
}: TemplateDetailModalProps) {
  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-zinc-900 border border-zinc-800 rounded max-w-3xl w-full max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between p-4 border-b border-zinc-800">
          <div>
            <h2 className="text-lg font-semibold">{template.name}</h2>
            <div className="text-xs text-zinc-500 mt-1">
              by {template.author} · v{template.version} · {template.downloads_count} downloads
            </div>
          </div>
          <div className="flex items-center gap-2">
            <RiskBadge level={template.risk_level} />
            <button
              onClick={onClose}
              className="px-2 py-1 text-xs rounded hover:bg-zinc-800"
            >
              Close
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="p-4 space-y-4">
          {/* Sandbox warning — master prompt §52 */}
          <div className="px-3 py-2 rounded border border-amber-500/40 bg-amber-500/10 text-amber-400 text-xs">
            Imported workflows must be sandboxed and permission-scanned (master
            prompt §52). This workflow will be installed with{" "}
            <span className="font-mono">enabled=false</span> — you must
            manually review and enable it before any node can run.
          </div>

          {/* Description */}
          <div>
            <div className="text-xs uppercase tracking-wider text-zinc-500 mb-1">
              Description
            </div>
            <p className="text-sm text-zinc-300">{template.description}</p>
          </div>

          {/* Tags */}
          {template.tags.length > 0 && (
            <div>
              <div className="text-xs uppercase tracking-wider text-zinc-500 mb-1">
                Tags
              </div>
              <div className="flex flex-wrap gap-1">
                {template.tags.map((tag) => (
                  <span
                    key={tag}
                    className="px-2 py-0.5 text-xs rounded bg-zinc-800 text-zinc-400"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Required permissions — master prompt §51 */}
          <div>
            <div className="text-xs uppercase tracking-wider text-zinc-500 mb-1">
              Required Permissions ({template.permissions_required.length})
            </div>
            {template.permissions_required.length === 0 ? (
              <div className="text-xs text-zinc-500">
                No tool-level permissions required.
              </div>
            ) : (
              <ul className="grid grid-cols-2 gap-1 text-xs">
                {template.permissions_required.map((perm) => (
                  <li
                    key={perm}
                    className="px-2 py-1 rounded bg-zinc-800 text-zinc-300 font-mono"
                  >
                    {perm}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Workflow preview */}
          <div>
            <div className="text-xs uppercase tracking-wider text-zinc-500 mb-1">
              Workflow Preview ({template.workflow.nodes.length} nodes)
            </div>
            <ol className="space-y-1 text-xs">
              {template.workflow.nodes.map((node, idx) => (
                <li
                  key={node.id}
                  className="px-2 py-1 rounded bg-zinc-950 border border-zinc-800"
                >
                  <span className="text-zinc-500 mr-2">{idx + 1}.</span>
                  <span className="font-mono text-zinc-300">{node.type}</span>
                  <span className="text-zinc-600 ml-2">#{node.id}</span>
                </li>
              ))}
            </ol>
          </div>

          {/* Install error */}
          {installError && (
            <div className="px-3 py-2 rounded border border-red-500/40 bg-red-500/10 text-red-400 text-xs">
              {installError}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-zinc-800 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button
            onClick={onInstall}
            disabled={installing}
            className="px-3 py-1.5 text-sm rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50"
          >
            {installing ? "Installing..." : "Install Workflow"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SubmitForm
// ---------------------------------------------------------------------------

interface SubmitFormProps {
  categories: MarketplaceCategory[];
  onSubmitted: () => void;
}

function SubmitForm({ categories, onSubmitted }: SubmitFormProps) {
  const [name, setName] = useState<string>("");
  const [description, setDescription] = useState<string>("");
  const [category, setCategory] = useState<string>(categories[0]?.category || "");
  const [tagsInput, setTagsInput] = useState<string>("");
  const [workflowJson, setWorkflowJson] = useState<string>("");
  const [author, setAuthor] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<boolean>(false);

  async function handleSubmit() {
    setError(null);
    if (!name.trim() || !workflowJson.trim() || !category) {
      setError("Name, category, and workflow JSON are required.");
      return;
    }
    let workflow: Workflow;
    try {
      workflow = JSON.parse(workflowJson);
    } catch (exc) {
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
    } catch (exc) {
      setError(`Submit failed: ${exc}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="p-4 rounded border border-zinc-800 bg-zinc-900 space-y-3">
      <div className="text-sm font-medium">Submit a new template</div>
      <div className="grid grid-cols-2 gap-3">
        <label className="text-xs text-zinc-500">
          Name
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 w-full px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-sm"
          />
        </label>
        <label className="text-xs text-zinc-500">
          Author
          <input
            type="text"
            value={author}
            onChange={(e) => setAuthor(e.target.value)}
            placeholder="anonymous"
            className="mt-1 w-full px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-sm"
          />
        </label>
        <label className="text-xs text-zinc-500">
          Category
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="mt-1 w-full px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-sm"
          >
            {categories.map((c) => (
              <option key={c.category} value={c.category}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-zinc-500">
          Tags (comma-separated)
          <input
            type="text"
            value={tagsInput}
            onChange={(e) => setTagsInput(e.target.value)}
            placeholder="tag1, tag2"
            className="mt-1 w-full px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-sm"
          />
        </label>
      </div>
      <label className="block text-xs text-zinc-500">
        Description
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          className="mt-1 w-full px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-sm"
        />
      </label>
      <label className="block text-xs text-zinc-500">
        Workflow JSON (paste the full Workflow object)
        <textarea
          value={workflowJson}
          onChange={(e) => setWorkflowJson(e.target.value)}
          rows={6}
          placeholder='{"id": "...", "name": "...", "nodes": [...], "trigger": {...}}'
          className="mt-1 w-full px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-sm font-mono"
        />
      </label>
      {error && (
        <div className="text-xs text-red-400 px-2 py-1 rounded bg-red-500/10 border border-red-500/40">
          {error}
        </div>
      )}
      <div className="flex justify-end gap-2">
        <button
          onClick={handleSubmit}
          disabled={submitting}
          className="px-3 py-1.5 text-sm rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50"
        >
          {submitting ? "Submitting..." : "Submit Template"}
        </button>
      </div>
    </div>
  );
}
