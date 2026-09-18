/**
 * Files page — master prompt §18 (file automation), §55 (file security).
 *
 * File manager UI: path breadcrumbs, file list with icons, click a folder
 * to navigate into it, click a file to preview (text inline, images as
 * thumbnails, PDFs are downloaded), and a context menu with rename, move,
 * copy, delete, download.
 *
 * Path safety is enforced by the backend — only Documents, Downloads,
 * Desktop, Pictures, and the project download/upload/workflows/templates
 * directories are allowed. Blocked paths (/etc, /usr, C:/Windows, ...)
 * return 403 and the UI renders a red banner.
 */

import React, { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";

interface FileEntry {
  name: string;
  path: string;
  relative: string;
  is_dir: boolean;
  size: number;
  modified_at: string;
  extension: string;
}

const ALLOWED_ROOTS = [
  "Documents",
  "Downloads",
  "Desktop",
  "Pictures",
  "project/download",
  "project/upload",
  "project/workflows",
  "project/templates",
];

export function Files() {
  const mockMode = useStore((s) => s.mockMode);
  const [path, setPath] = useState("~/Downloads");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string>("");
  const [search, setSearch] = useState("");
  const [preview, setPreview] = useState<{ name: string; text?: string; error?: string } | null>(null);
  const [menu, setMenu] = useState<{ entry: FileEntry; x: number; y: number } | null>(null);

  async function load(target?: string) {
    setStatus("loading");
    setError("");
    try {
      const r = await api.files.list(target ?? path);
      setPath(r.path);
      setEntries((r.entries as FileEntry[]) ?? []);
      setStatus("ready");
    } catch (e) {
      setError(String(e));
      setStatus("error");
    }
  }

  useEffect(() => {
    load("~/Downloads");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    function closeMenu() {
      setMenu(null);
    }
    if (menu) {
      window.addEventListener("click", closeMenu);
      return () => window.removeEventListener("click", closeMenu);
    }
  }, [menu]);

  const breadcrumbs = useMemo(() => {
    const parts = path.split("/").filter(Boolean);
    return parts.map((p, i) => ({
      label: p,
      full: "/" + parts.slice(0, i + 1).join("/"),
    }));
  }, [path]);

  const filtered = useMemo(() => {
    if (!search) return entries;
    const q = search.toLowerCase();
    return entries.filter((e) => e.name.toLowerCase().includes(q));
  }, [entries, search]);

  async function handleClick(entry: FileEntry) {
    if (entry.is_dir) {
      await load(entry.path);
      setPreview(null);
      return;
    }
    // Preview text files.
    if ([".txt", ".md", ".json", ".csv", ".py", ".ts", ".tsx", ".js", ".jsx", ".yml", ".yaml", ".toml", ".ini", ".env"].includes(entry.extension)) {
      try {
        const r = await api.files.read(entry.path);
        setPreview({ name: entry.name, text: r.text });
      } catch (e) {
        setPreview({ name: entry.name, error: String(e) });
      }
      return;
    }
    // Images + PDFs: trigger download.
    try {
      const blob = await api.files.download(entry.path);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = entry.name;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setPreview({ name: entry.name, error: String(e) });
    }
  }

  async function handleContext(e: React.MouseEvent, entry: FileEntry) {
    e.preventDefault();
    setMenu({ entry, x: e.clientX, y: e.clientY });
  }

  async function handleAction(action: string, entry: FileEntry) {
    setMenu(null);
    if (action === "rename") {
      const newName = window.prompt("New name:", entry.name);
      if (!newName || newName === entry.name) return;
      try {
        await api.files.rename(entry.path, newName);
        await load();
      } catch (e) {
        setError(String(e));
      }
      return;
    }
    if (action === "move") {
      const dest = window.prompt("Destination path:", entry.path);
      if (!dest) return;
      try {
        await api.files.move(entry.path, dest);
        await load();
      } catch (e) {
        setError(String(e));
      }
      return;
    }
    if (action === "copy") {
      const dest = window.prompt("Destination path:", entry.path + ".copy");
      if (!dest) return;
      try {
        await api.files.copy(entry.path, dest);
        await load();
      } catch (e) {
        setError(String(e));
      }
      return;
    }
    if (action === "delete") {
      const ok = window.confirm(`Delete ${entry.name}? This cannot be undone.`);
      if (!ok) return;
      try {
        await api.files.delete(entry.path, true);
        await load();
      } catch (e) {
        setError(String(e));
      }
      return;
    }
    if (action === "download") {
      try {
        const blob = await api.files.download(entry.path);
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = entry.name;
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        setError(String(e));
      }
    }
  }

  async function handleNewFolder() {
    const name = window.prompt("New folder name:", "New Folder");
    if (!name) return;
    const target = path.endsWith("/") ? path + name : path + "/" + name;
    try {
      // Create an empty placeholder file inside the new folder so it materializes.
      await api.files.write(target + "/.keep", "");
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handlePathSubmit(e: React.FormEvent) {
    e.preventDefault();
    await load();
  }

  function iconFor(entry: FileEntry) {
    if (entry.is_dir) return "F";
    if ([".png", ".jpg", ".jpeg", ".gif", ".webp"].includes(entry.extension)) return "I";
    if (entry.extension === ".pdf") return "P";
    return "T";
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Files</h1>
        <p className="text-zinc-400 mt-1">
          Browse allowed directories. Blocked paths are rejected at the API layer.
        </p>
      </div>

      <div className="bg-blue-900/20 border border-blue-700 rounded-lg p-3 text-xs text-blue-200">
        Only allowed directories: {ALLOWED_ROOTS.join(", ")}.
        Blocked paths (/etc, /usr, /bin, C:/Windows, ...) return 403.
      </div>

      {mockMode && (
        <div className="bg-amber-900/20 border border-amber-700 rounded-lg p-3 text-xs text-amber-300">
          File operations are running in mock mode — writes are still real (no
          mock layer in the file tools), but the recorder / browser pipelines
          will not fire OS events.
        </div>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Toolbar */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3 space-y-2">
        <form onSubmit={handlePathSubmit} className="flex gap-2">
          <input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            className="flex-1 bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm font-mono"
            placeholder="~/Downloads"
          />
          <button type="submit" className="bg-zinc-700 hover:bg-zinc-600 rounded px-3 py-1.5 text-sm">
            Go
          </button>
          <button
            type="button"
            onClick={handleNewFolder}
            className="bg-zinc-700 hover:bg-zinc-600 rounded px-3 py-1.5 text-sm"
          >
            New Folder
          </button>
          <button
            type="button"
            onClick={() => load()}
            className="bg-zinc-700 hover:bg-zinc-600 rounded px-3 py-1.5 text-sm"
          >
            Refresh
          </button>
        </form>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter by name..."
          className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm"
        />
      </div>

      {/* Breadcrumbs */}
      <div className="flex items-center gap-1 text-sm text-zinc-400">
        <button
          onClick={() => load("~/Downloads")}
          className="hover:text-zinc-200"
        >
          ~
        </button>
        {breadcrumbs.map((b, i) => (
          <React.Fragment key={i}>
            <span className="text-zinc-600">/</span>
            <button
              onClick={() => load(b.full)}
              className="hover:text-zinc-200"
            >
              {b.label}
            </button>
          </React.Fragment>
        ))}
      </div>

      <div className="grid grid-cols-12 gap-4">
        {/* File list */}
        <div className={`bg-zinc-900 border border-zinc-800 rounded-lg ${preview ? "col-span-7" : "col-span-12"}`}>
          <div className="px-3 py-2 border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500 flex justify-between">
            <span>{filtered.length} item(s)</span>
            <span>Right-click for menu</span>
          </div>
          <div className="divide-y divide-zinc-800 max-h-[600px] overflow-y-auto">
            {status === "loading" ? (
              <div className="px-4 py-8 text-center text-zinc-500 text-sm">Loading...</div>
            ) : filtered.length === 0 ? (
              <div className="px-4 py-8 text-center text-zinc-500 text-sm">
                No files found.
              </div>
            ) : (
              filtered.map((e) => (
                <div
                  key={e.path}
                  onClick={() => handleClick(e)}
                  onContextMenu={(ev) => handleContext(ev, e)}
                  className="px-3 py-2 flex items-center gap-3 hover:bg-zinc-800 cursor-pointer"
                >
                  <span className="w-6 text-center text-xs font-mono text-zinc-400">
                    {iconFor(e)}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className={`text-sm truncate ${e.is_dir ? "text-zinc-200" : "text-zinc-300"}`}>
                      {e.name}
                    </div>
                    <div className="text-xs text-zinc-500">
                      {e.is_dir ? "Directory" : `${e.size.toLocaleString()} bytes`}
                      {" — "}
                      {new Date(e.modified_at).toLocaleString()}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Preview */}
        {preview && (
          <div className="col-span-5 bg-zinc-900 border border-zinc-800 rounded-lg flex flex-col">
            <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between">
              <span className="text-sm font-medium truncate">{preview.name}</span>
              <button
                onClick={() => setPreview(null)}
                className="text-xs text-zinc-500 hover:text-zinc-300"
              >
                Close
              </button>
            </div>
            <div className="flex-1 overflow-auto p-3">
              {preview.error ? (
                <div className="text-sm text-red-400">{preview.error}</div>
              ) : (
                <pre className="text-xs font-mono text-zinc-300 whitespace-pre-wrap break-all">
                  {preview.text}
                </pre>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Context menu */}
      {menu && (
        <div
          className="fixed z-50 bg-zinc-900 border border-zinc-700 rounded shadow-lg py-1 text-sm"
          style={{ left: menu.x, top: menu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => handleAction("rename", menu.entry)}
            className="w-full text-left px-3 py-1.5 hover:bg-zinc-800"
          >
            Rename
          </button>
          <button
            onClick={() => handleAction("move", menu.entry)}
            className="w-full text-left px-3 py-1.5 hover:bg-zinc-800"
          >
            Move
          </button>
          <button
            onClick={() => handleAction("copy", menu.entry)}
            className="w-full text-left px-3 py-1.5 hover:bg-zinc-800"
          >
            Copy
          </button>
          <button
            onClick={() => handleAction("download", menu.entry)}
            className="w-full text-left px-3 py-1.5 hover:bg-zinc-800"
          >
            Download
          </button>
          <div className="border-t border-zinc-700 my-1" />
          <button
            onClick={() => handleAction("delete", menu.entry)}
            className="w-full text-left px-3 py-1.5 hover:bg-red-900/40 text-red-300"
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}
