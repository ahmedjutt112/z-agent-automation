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
} as const;

contextBridge.exposeInMainWorld("zai", api);

// Type declaration for the renderer — referenced by renderer/src/types/window.d.ts
export type ZaiAPI = typeof api;
