/** Window type declaration for the renderer. */
export type TrayState = "idle" | "running" | "paused" | "error";

export interface ZaiAPI {
  ping: () => Promise<{
    status: string;
    service: string;
    version: string;
    mock_mode: boolean;
    kill_switch: boolean;
  }>;
  emergencyStop: () => Promise<{ engaged: boolean }>;
  windowClose: () => void;
  windowMinimize: () => void;
  /** Tray state sync (master prompt section 47). */
  traySetState: (state: TrayState) => Promise<{ ok: boolean; state: TrayState }>;
  trayRefresh: () => Promise<{ ok: boolean }>;
  /** Tray -> renderer event subscriptions. Each returns an unsubscribe. */
  onTrayPause: (cb: () => void) => () => void;
  onTrayResume: (cb: () => void) => () => void;
  onTrayEmergencyStop: (cb: () => void) => () => void;
  onTrayOpenSettings: (cb: () => void) => () => void;
}

declare global {
  interface Window {
    zai: ZaiAPI;
  }
}

export {};
