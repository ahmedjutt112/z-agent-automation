"use strict";
/**
 * Electron main process — master prompt §4, §55.
 *
 * CRITICAL SECURITY RULES (per §55 Electron Security):
 *   - contextIsolation: true
 *   - nodeIntegration: false
 *   - sandbox: true
 *   - Strict CSP via response headers
 *   - Validate ALL IPC payloads with zod schemas
 *   - Never expose unrestricted Node.js APIs to the renderer
 *
 * The Electron main process spawns the Python automation service as a
 * child process and proxies renderer ↔ service traffic over a typed IPC.
 */
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
const electron_1 = require("electron");
const node_child_process_1 = require("node:child_process");
const path = __importStar(require("node:path"));
// System tray — master prompt section 47
const tray_1 = require("./tray");
let automationProc = null;
let mainWindow = null;
const AUTOMATION_HOST = "127.0.0.1";
const AUTOMATION_PORT = 8765;
// ---------------------------------------------------------------------------
// CSP — strict, master prompt §55
// ---------------------------------------------------------------------------
const CSP_HEADER = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'", // Tailwind requires inline styles
    "img-src 'self' data:",
    "connect-src 'self' http://127.0.0.1:8765 ws://127.0.0.1:8765",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "form-action 'self'",
].join("; ");
// ---------------------------------------------------------------------------
// Spawn the Python automation service (master prompt §5)
// ---------------------------------------------------------------------------
function spawnAutomationService() {
    const pyPath = process.env.PYTHON_BIN || "python";
    const scriptPath = path.join(__dirname, "..", "..", "..", "apps", "automation-service", "automation_service", "main.py");
    // Don't spawn if running uvicorn directly is preferable
    try {
        const proc = (0, node_child_process_1.spawn)(pyPath, ["-m", "uvicorn", "automation_service.main:app", "--host", AUTOMATION_HOST, "--port", String(AUTOMATION_PORT)], {
            cwd: path.join(__dirname, "..", "..", "..", "apps", "automation-service"),
            stdio: ["ignore", "pipe", "pipe"],
            env: { ...process.env, PYTHONUNBUFFERED: "1" },
        });
        proc.stdout?.on("data", (chunk) => {
            console.log(`[automation-service] ${chunk.toString().trim()}`);
        });
        proc.stderr?.on("data", (chunk) => {
            console.error(`[automation-service] ${chunk.toString().trim()}`);
        });
        proc.on("exit", (code) => {
            console.log(`[automation-service] exited with code ${code}`);
            automationProc = null;
        });
        return proc;
    }
    catch (err) {
        console.error("Failed to spawn automation service:", err);
        return null;
    }
}
// ---------------------------------------------------------------------------
// Window creation
// ---------------------------------------------------------------------------
function createWindow() {
    mainWindow = new electron_1.BrowserWindow({
        width: 1440,
        height: 900,
        minWidth: 1024,
        minHeight: 700,
        title: "AI PC/Laptop Automation Agent",
        backgroundColor: "#0f1115",
        show: false,
        titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "default",
        webPreferences: {
            preload: path.join(__dirname, "preload.js"),
            contextIsolation: true, // §55 — REQUIRED
            nodeIntegration: false, // §55 — REQUIRED false
            sandbox: true, // §55 — REQUIRED true
            devTools: process.env.NODE_ENV === "development",
        },
    });
    mainWindow.once("ready-to-show", () => {
        mainWindow?.show();
    });
    // Open external links in default browser, not in-app
    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
        electron_1.shell.openExternal(url);
        return { action: "deny" };
    });
    if (process.env.NODE_ENV === "development") {
        mainWindow.loadURL("http://localhost:5173");
    }
    else {
        mainWindow.loadFile(path.join(__dirname, "..", "renderer", "dist", "index.html"));
    }
}
electron_1.ipcMain.handle("automation:ping", async () => {
    try {
        const resp = await fetch(`http://${AUTOMATION_HOST}:${AUTOMATION_PORT}/health`);
        return await resp.json();
    }
    catch (err) {
        throw new Error(`Automation service unreachable: ${err.message}`);
    }
});
electron_1.ipcMain.handle("automation:emergency-stop", async () => {
    const resp = await fetch(`http://${AUTOMATION_HOST}:${AUTOMATION_PORT}/emergency-stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
    });
    return await resp.json();
});
// ---------------------------------------------------------------------------
// Tray state sync — renderer pushes state changes from the WebSocket
// event stream (TASK_STARTED -> running, TASK_PAUSED -> paused, etc.).
// ---------------------------------------------------------------------------
electron_1.ipcMain.handle("tray:set-state", async (_evt, state) => {
    (0, tray_1.setTrayState)(state, mainWindow);
    return { ok: true, state };
});
electron_1.ipcMain.handle("tray:refresh", async () => {
    await (0, tray_1.refreshTrayMenu)(mainWindow);
    return { ok: true };
});
// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------
electron_1.app.whenReady().then(() => {
    // Apply CSP
    electron_1.session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
        callback({
            responseHeaders: {
                ...details.responseHeaders,
                "Content-Security-Policy": [CSP_HEADER],
            },
        });
    });
    automationProc = spawnAutomationService();
    createWindow();
    // System tray — master prompt section 47. Must be set up AFTER the
    // window is created because the tray menu items toggle the window.
    (0, tray_1.setupTray)(mainWindow);
    electron_1.app.on("activate", () => {
        if (electron_1.BrowserWindow.getAllWindows().length === 0)
            createWindow();
    });
});
electron_1.app.on("window-all-closed", () => {
    // Hide the tray when all windows close (don't quit unless the user
    // explicitly clicked Exit in the tray menu). On macOS this is the
    // conventional behavior; on Linux/Windows we mirror it so the tray
    // remains the primary control surface.
    (0, tray_1.destroyTray)();
    if (automationProc) {
        automationProc.kill("SIGTERM");
        automationProc = null;
    }
    if (process.platform !== "darwin")
        electron_1.app.quit();
});
electron_1.app.on("before-quit", () => {
    (0, tray_1.destroyTray)();
    if (automationProc) {
        automationProc.kill("SIGTERM");
        automationProc = null;
    }
});
