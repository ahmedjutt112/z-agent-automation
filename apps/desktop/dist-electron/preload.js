"use strict";
/**
 * Preload script — master prompt §55.
 *
 * Exposes a SAFE, minimal API to the renderer via contextBridge.
 * NEVER expose unrestricted Node.js / Electron APIs.
 */
Object.defineProperty(exports, "__esModule", { value: true });
const electron_1 = require("electron");
const api = {
    ping: () => electron_1.ipcRenderer.invoke("automation:ping"),
    emergencyStop: () => electron_1.ipcRenderer.invoke("automation:emergency-stop"),
    // Renderer can request its own window actions (close/minimize)
    windowClose: () => electron_1.ipcRenderer.send("window:close"),
    windowMinimize: () => electron_1.ipcRenderer.send("window:minimize"),
    // Tray state sync (master prompt section 47) — renderer pushes state
    // changes from the WebSocket event stream (TASK_STARTED -> running,
    // TASK_PAUSED -> paused, TASK_COMPLETED -> idle). The main process
    // owns the actual Tray instance; this is just a notification channel.
    traySetState: (state) => electron_1.ipcRenderer.invoke("tray:set-state", state),
    trayRefresh: () => electron_1.ipcRenderer.invoke("tray:refresh"),
    // Tray -> renderer signals (the tray menu emits these so the UI
    // can react to Open Agent / Pause / Resume / Open Settings clicks).
    onTrayPause: (cb) => {
        const handler = () => cb();
        electron_1.ipcRenderer.on("tray:pause-automation", handler);
        return () => electron_1.ipcRenderer.removeListener("tray:pause-automation", handler);
    },
    onTrayResume: (cb) => {
        const handler = () => cb();
        electron_1.ipcRenderer.on("tray:resume-automation", handler);
        return () => electron_1.ipcRenderer.removeListener("tray:resume-automation", handler);
    },
    onTrayEmergencyStop: (cb) => {
        const handler = () => cb();
        electron_1.ipcRenderer.on("tray:emergency-stop", handler);
        return () => electron_1.ipcRenderer.removeListener("tray:emergency-stop", handler);
    },
    onTrayOpenSettings: (cb) => {
        const handler = () => cb();
        electron_1.ipcRenderer.on("tray:open-settings", handler);
        return () => electron_1.ipcRenderer.removeListener("tray:open-settings", handler);
    },
};
electron_1.contextBridge.exposeInMainWorld("zai", api);
