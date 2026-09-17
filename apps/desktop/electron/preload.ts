/**
 * Preload script — master prompt §55.
 *
 * Exposes a SAFE, minimal API to the renderer via contextBridge.
 * NEVER expose unrestricted Node.js / Electron APIs.
 */

import { contextBridge, ipcRenderer } from "electron";

const api = {
  ping: () => ipcRenderer.invoke("automation:ping"),
  emergencyStop: () => ipcRenderer.invoke("automation:emergency-stop"),
  // Renderer can request its own window actions (close/minimize)
  windowClose: () => ipcRenderer.send("window:close"),
  windowMinimize: () => ipcRenderer.send("window:minimize"),
  // Tray state sync (master prompt section 47) — renderer pushes state
  // changes from the WebSocket event stream (TASK_STARTED -> running,
  // TASK_PAUSED -> paused, TASK_COMPLETED -> idle). The main process
  // owns the actual Tray instance; this is just a notification channel.
  traySetState: (state: "idle" | "running" | "paused" | "error") =>
    ipcRenderer.invoke("tray:set-state", state),
  trayRefresh: () => ipcRenderer.invoke("tray:refresh"),
  // Tray -> renderer signals (the tray menu emits these so the UI
  // can react to Open Agent / Pause / Resume / Open Settings clicks).
  onTrayPause: (cb: () => void) => {
    const handler = () => cb();
    ipcRenderer.on("tray:pause-automation", handler);
    return () => ipcRenderer.removeListener("tray:pause-automation", handler);
  },
  onTrayResume: (cb: () => void) => {
    const handler = () => cb();
    ipcRenderer.on("tray:resume-automation", handler);
    return () => ipcRenderer.removeListener("tray:resume-automation", handler);
  },
  onTrayEmergencyStop: (cb: () => void) => {
    const handler = () => cb();
    ipcRenderer.on("tray:emergency-stop", handler);
    return () => ipcRenderer.removeListener("tray:emergency-stop", handler);
  },
  onTrayOpenSettings: (cb: () => void) => {
    const handler = () => cb();
    ipcRenderer.on("tray:open-settings", handler);
    return () => ipcRenderer.removeListener("tray:open-settings", handler);
  },
} as const;

contextBridge.exposeInMainWorld("zai", api);

// Type declaration for the renderer — referenced by renderer/src/types/window.d.ts
export type ZaiAPI = typeof api;
