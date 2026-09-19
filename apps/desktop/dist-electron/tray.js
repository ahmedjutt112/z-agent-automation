"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.createTrayIcon = createTrayIcon;
exports.buildTrayMenu = buildTrayMenu;
exports.setupTray = setupTray;
exports.destroyTray = destroyTray;
exports.setTrayState = setTrayState;
exports.refreshTrayMenu = refreshTrayMenu;
/**
 * System tray — master prompt section 47.
 *
 * This module is responsible for:
 *
 *   1. Programmatically generating the tray icon PNG (no external image
 *      files required — works in dev, packaged, and asar-packed builds).
 *   2. Building the tray context menu (Open / Pause / Resume / Emergency
 *      Stop / Run Workflow / Recent Tasks / Settings / Exit).
 *   3. Reflecting the automation service's state in the icon color
 *      (green=idle, red=running, yellow=paused, dark red=error).
 *   4. Wiring up left/right click behavior on the tray icon itself.
 *
 * The icon is generated as a 16x16 PNG via a small hand-rolled PNG
 * encoder so we have zero external image dependencies. Color state is
 * applied by re-rendering the icon whenever ``setTrayState`` is called.
 *
 * Master prompt section 47 requirements honored here:
 *   - Tray icon reflects automation state (green/red/yellow).
 *   - Left-click toggles window visibility; right-click opens menu.
 *   - Emergency Stop tray entry hits POST /emergency-stop on the
 *     automation service (loopback only — never exposed externally).
 *   - Run Workflow submenu lists the 5 most recent saved workflows,
 *     fetched from GET /workflow on the automation service.
 *
 * NOTE: This file is imported from ``main.ts`` AFTER ``app.whenReady()``
 * fires — ``Tray`` can only be instantiated once the app is ready.
 */
const electron_1 = require("electron");
const zlib = __importStar(require("node:zlib"));
// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const AUTOMATION_HOST = "127.0.0.1";
const AUTOMATION_PORT = 8765;
const AUTOMATION_BASE = `http://${AUTOMATION_HOST}:${AUTOMATION_PORT}`;
/** Tray icon canvas size — 16x16 is the smallest cross-platform tray size. */
const ICON_SIZE = 16;
// ---------------------------------------------------------------------------
// PNG generation — minimal hand-rolled PNG encoder (no external deps)
// ---------------------------------------------------------------------------
/**
 * RGBA color lookup for each tray state.
 *
 *   idle    -> green   (automation ready, no task running)
 *   running -> red     (a task is actively executing)
 *   paused  -> yellow  (automation paused via the tray menu)
 *   error   -> darkred (kill switch engaged or service unreachable)
 */
const STATE_COLORS = {
    idle: [0x22, 0xc5, 0x5e], // emerald-500
    running: [0xef, 0x44, 0x44], // red-500
    paused: [0xf5, 0x9e, 0x0b], // amber-500
    error: [0x99, 0x1b, 0x1b], // red-800
};
/**
 * Render a 16x16 RGBA bitmap of a colored circle on a transparent
 * background. The circle has a 1px dark outline so it stays visible on
 * both light and dark menu bars.
 *
 * Pure function — no side effects. Used by ``createTrayIcon`` to get
 * the raw pixel buffer before PNG-encoding it.
 */
function renderStateBitmap(state) {
    const [r, g, b] = STATE_COLORS[state];
    const size = ICON_SIZE;
    const buf = Buffer.alloc(size * size * 4); // RGBA
    const cx = (size - 1) / 2;
    const cy = (size - 1) / 2;
    const innerR = size / 2 - 2; // filled disc radius
    const outerR = size / 2 - 1; // outline radius
    for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
            const dx = x - cx;
            const dy = y - cy;
            const dist = Math.sqrt(dx * dx + dy * dy);
            const idx = (y * size + x) * 4;
            if (dist <= innerR) {
                // Inner disc — solid state color
                buf[idx] = r;
                buf[idx + 1] = g;
                buf[idx + 2] = b;
                buf[idx + 3] = 0xff;
            }
            else if (dist <= outerR) {
                // 1px outline — dark for contrast on any backdrop
                buf[idx] = 0x1a;
                buf[idx + 1] = 0x1a;
                buf[idx + 2] = 0x1a;
                buf[idx + 3] = 0xff;
            }
            // Otherwise leave the pixel fully transparent (alpha=0).
        }
    }
    return buf;
}
/**
 * Encode an RGBA buffer to a PNG file using only stdlib (zlib).
 *
 * We hand-build the PNG chunks: IHDR, IDAT (zlib-compressed scanlines
 * with a per-row filter byte of 0), IEND. CRC32 is computed per chunk.
 *
 * @param rgba   Buffer of length ``size*size*4`` (RGBA, row-major)
 * @param size   Width/height in pixels
 */
function encodePng(rgba, size) {
    // Per-row filter byte (0 = None) prepended to each scanline.
    const stride = size * 4;
    const raw = Buffer.alloc((stride + 1) * size);
    for (let y = 0; y < size; y++) {
        raw[y * (stride + 1)] = 0; // filter byte
        rgba.copy(raw, y * (stride + 1) + 1, y * stride, y * stride + stride);
    }
    const idatData = zlib.deflateSync(raw);
    // PNG signature
    const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
    // IHDR
    const ihdr = Buffer.alloc(13);
    ihdr.writeUInt32BE(size, 0); // width
    ihdr.writeUInt32BE(size, 4); // height
    ihdr.writeUInt8(8, 8); // bit depth
    ihdr.writeUInt8(6, 9); // color type: RGBA
    ihdr.writeUInt8(0, 10); // compression: deflate
    ihdr.writeUInt8(0, 11); // filter method: standard
    ihdr.writeUInt8(0, 12); // interlace: none
    const chunks = [sig];
    chunks.push(makeChunk("IHDR", ihdr));
    chunks.push(makeChunk("IDAT", idatData));
    chunks.push(makeChunk("IEND", Buffer.alloc(0)));
    return Buffer.concat(chunks);
}
/** Build a single PNG chunk with its length, type, data, and CRC32. */
function makeChunk(type, data) {
    const typeBuf = Buffer.from(type, "ascii");
    const lenBuf = Buffer.alloc(4);
    lenBuf.writeUInt32BE(data.length, 0);
    const crcBuf = Buffer.alloc(4);
    const crc = crc32(Buffer.concat([typeBuf, data]));
    crcBuf.writeUInt32BE(crc >>> 0, 0);
    return Buffer.concat([lenBuf, typeBuf, data, crcBuf]);
}
/** Standard CRC32 table + polynomial used by PNG chunks. */
const CRC_TABLE = (() => {
    const table = new Array(256);
    for (let n = 0; n < 256; n++) {
        let c = n;
        for (let k = 0; k < 8; k++) {
            c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
        }
        table[n] = c >>> 0;
    }
    return table;
})();
function crc32(buf) {
    let c = 0xffffffff;
    for (let i = 0; i < buf.length; i++) {
        c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
    }
    return (c ^ 0xffffffff) >>> 0;
}
/**
 * Create a 16x16 ``nativeImage`` reflecting ``state``. The image is
 * generated entirely in-memory — no external asset files required.
 *
 * Used both for the initial tray icon and for ``setImage`` after a
 * state change.
 */
function createTrayIcon(state = "idle") {
    const rgba = renderStateBitmap(state);
    const png = encodePng(rgba, ICON_SIZE);
    const img = electron_1.nativeImage.createFromBuffer(png, { width: ICON_SIZE, height: ICON_SIZE });
    // Mark as a template image on macOS so it adapts to dark/light menu bars.
    img.setTemplateImage(false);
    return img;
}
// ---------------------------------------------------------------------------
// Tray menu construction
// ---------------------------------------------------------------------------
/**
 * Build the tray context menu.
 *
 * ``workflows`` is the list of recent workflow summaries (already fetched
 * from the automation service) — they're surfaced as a "Run Workflow"
 * submenu. ``state`` controls which items are enabled (Pause is disabled
 * when already paused; Resume is disabled when not paused).
 *
 * All actions are wired to either IPC channels (renderer-side automation
 * state changes) or HTTP calls to the automation service.
 */
function buildTrayMenu(window, state, workflows = [], tasks = []) {
    const isPaused = state === "paused";
    const isRunning = state === "running";
    const workflowSubmenu = workflows.length === 0
        ? [{ label: "(none)", enabled: false }]
        : workflows.slice(0, 5).map((wf) => ({
            label: wf.name,
            click: () => {
                void runWorkflowById(wf.id, window);
            },
        }));
    const taskSubmenu = tasks.length === 0
        ? [{ label: "(none)", enabled: false }]
        : tasks.slice(0, 5).map((t) => ({
            label: `${t.name} — ${t.status}`,
            click: () => {
                showWindow(window);
                window?.webContents.send("tray:open-task", t.id);
            },
        }));
    const template = [
        {
            label: "Open Agent",
            click: () => showWindow(window),
        },
        { type: "separator" },
        {
            label: "Pause Automation",
            enabled: !isPaused,
            click: () => {
                window?.webContents.send("tray:pause-automation");
                setTrayState("paused");
            },
        },
        {
            label: "Resume",
            enabled: isPaused,
            click: () => {
                window?.webContents.send("tray:resume-automation");
                setTrayState("idle");
            },
        },
        { type: "separator" },
        {
            label: "Emergency Stop",
            click: () => {
                void emergencyStop(window);
            },
        },
        { type: "separator" },
        {
            label: "Run Workflow",
            type: "submenu",
            submenu: workflowSubmenu,
        },
        {
            label: "Recent Tasks",
            type: "submenu",
            submenu: taskSubmenu,
        },
        { type: "separator" },
        {
            label: "Settings",
            click: () => {
                showWindow(window);
                window?.webContents.send("tray:open-settings");
            },
        },
        { type: "separator" },
        {
            label: "Exit",
            click: () => {
                // Defer the import so this file is import-safe even before
                // the Electron app is ready.
                Promise.resolve().then(() => __importStar(require("electron"))).then(({ app }) => app.quit());
            },
        },
    ];
    return electron_1.Menu.buildFromTemplate(template);
}
// ---------------------------------------------------------------------------
// Tray setup + state management
// ---------------------------------------------------------------------------
let trayInstance = null;
let currentState = "idle";
/**
 * Set up the system tray. Should be called once after
 * ``app.whenReady()`` fires (typically from ``main.ts``).
 *
 * - Creates the tray icon using ``createTrayIcon("idle")``.
 * - Builds the initial menu via ``buildTrayMenu``.
 * - Wires up the click handlers:
 *     * left-click toggles the main window visibility
 *     * right-click shows the menu (default behavior on most platforms)
 *
 * Returns the created ``Tray`` instance. Subsequent calls reuse the
 * existing tray (idempotent).
 */
function setupTray(window) {
    if (trayInstance) {
        return trayInstance;
    }
    const tray = new electron_1.Tray(createTrayIcon(currentState));
    tray.setToolTip("AI PC/Laptop Automation Agent");
    // Build initial menu — workflows/tasks are empty until first refresh.
    tray.setContextMenu(buildTrayMenu(window, currentState));
    tray.on("click", () => {
        // Left-click toggles the window visibility.
        if (window) {
            if (window.isVisible() && !window.isMinimized()) {
                window.hide();
            }
            else {
                showWindow(window);
            }
        }
    });
    trayInstance = tray;
    // Kick off an async refresh of workflows + tasks so the submenu is
    // populated by the time the user first right-clicks. Errors are
    // swallowed — the tray is a UI affordance, not a critical path.
    void refreshTrayMenu(window).catch(() => {
        /* best effort */
    });
    return tray;
}
/** Tear down the tray (used on app shutdown / window-all-closed). */
function destroyTray() {
    if (trayInstance) {
        trayInstance.destroy();
        trayInstance = null;
    }
}
/**
 * Update the tray icon + menu to reflect a new automation state.
 *
 * Safe to call from any thread (Electron main). Called by:
 *   - the renderer when TASK_STARTED / TASK_PAUSED / TASK_COMPLETED
 *     events arrive over the WebSocket.
 *   - the menu item click handlers above.
 */
function setTrayState(state, window = null) {
    currentState = state;
    if (!trayInstance)
        return;
    trayInstance.setImage(createTrayIcon(state));
    trayInstance.setContextMenu(buildTrayMenu(window, state));
    const tooltipSuffix = state === "idle"
        ? "idle"
        : state === "running"
            ? "running"
            : state === "paused"
                ? "paused"
                : "error";
    trayInstance.setToolTip(`AI Automation Agent — ${tooltipSuffix}`);
}
/**
 * Re-fetch the 5 most recent workflows from the automation service and
 * rebuild the tray menu. Called periodically (every 60s) and after
 * workflow CRUD operations on the renderer side.
 *
 * In mock mode (service unreachable) the menu is rebuilt with empty
 * workflow/task lists rather than throwing.
 */
async function refreshTrayMenu(window) {
    let workflows = [];
    let tasks = [];
    try {
        const resp = await fetch(`${AUTOMATION_BASE}/workflow`, {
            headers: { "Content-Type": "application/json" },
        });
        if (resp.ok) {
            const data = (await resp.json());
            workflows = Array.isArray(data) ? data : [];
        }
    }
    catch {
        // Service unreachable — leave workflows empty (mock mode).
    }
    // Tasks placeholder — no /tasks endpoint exists yet; surface an empty
    // list rather than erroring. The Recent Tasks submenu will show
    // "(none)" until the task API is wired up.
    tasks = [];
    if (trayInstance) {
        trayInstance.setContextMenu(buildTrayMenu(window, currentState, workflows, tasks));
    }
}
// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------
function showWindow(window) {
    if (!window)
        return;
    if (window.isMinimized())
        window.restore();
    if (!window.isVisible())
        window.show();
    window.focus();
}
async function emergencyStop(window) {
    try {
        await fetch(`${AUTOMATION_BASE}/emergency-stop`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
        });
    }
    catch (err) {
        // Even if the service is unreachable, notify the renderer so the
        // user gets feedback that the tray button was clicked.
        console.error("[tray] emergency-stop failed:", err);
    }
    window?.webContents.send("tray:emergency-stop");
    setTrayState("error", window);
}
async function runWorkflowById(workflowId, window) {
    try {
        const resp = await fetch(`${AUTOMATION_BASE}/workflow/${workflowId}/run`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
        });
        if (resp.ok) {
            const result = (await resp.json());
            window?.webContents.send("tray:workflow-started", {
                workflow_id: workflowId,
                run_id: result.run_id,
            });
            setTrayState("running", window);
        }
    }
    catch (err) {
        console.error(`[tray] run workflow ${workflowId} failed:`, err);
    }
}
