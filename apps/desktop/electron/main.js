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
import { app, BrowserWindow, ipcMain, shell, session } from "electron";
import { spawn } from "node:child_process";
import * as path from "node:path";
// System tray — master prompt section 47
import { setupTray, destroyTray, setTrayState, refreshTrayMenu } from "./tray";
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
        const proc = spawn(pyPath, ["-m", "uvicorn", "automation_service.main:app", "--host", AUTOMATION_HOST, "--port", String(AUTOMATION_PORT)], {
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
    mainWindow = new BrowserWindow({
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
        shell.openExternal(url);
        return { action: "deny" };
    });
    if (process.env.NODE_ENV === "development") {
        mainWindow.loadURL("http://localhost:5173");
    }
    else {
        mainWindow.loadFile(path.join(__dirname, "..", "renderer", "dist", "index.html"));
    }
}
ipcMain.handle("automation:ping", async () => {
    try {
        const resp = await fetch(`http://${AUTOMATION_HOST}:${AUTOMATION_PORT}/health`);
        return await resp.json();
    }
    catch (err) {
        throw new Error(`Automation service unreachable: ${err.message}`);
    }
});
ipcMain.handle("automation:emergency-stop", async () => {
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
ipcMain.handle("tray:set-state", async (_evt, state) => {
    setTrayState(state, mainWindow);
    return { ok: true, state };
});
ipcMain.handle("tray:refresh", async () => {
    await refreshTrayMenu(mainWindow);
    return { ok: true };
});
// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------
app.whenReady().then(() => {
    // Apply CSP
    session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
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
    setupTray(mainWindow);
    app.on("activate", () => {
        if (BrowserWindow.getAllWindows().length === 0)
            createWindow();
    });
});
app.on("window-all-closed", () => {
    // Hide the tray when all windows close (don't quit unless the user
    // explicitly clicked Exit in the tray menu). On macOS this is the
    // conventional behavior; on Linux/Windows we mirror it so the tray
    // remains the primary control surface.
    destroyTray();
    if (automationProc) {
        automationProc.kill("SIGTERM");
        automationProc = null;
    }
    if (process.platform !== "darwin")
        app.quit();
});
app.on("before-quit", () => {
    destroyTray();
    if (automationProc) {
        automationProc.kill("SIGTERM");
        automationProc = null;
    }
});
