/** Window type declaration for the renderer. */
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
}

declare global {
  interface Window {
    zai: ZaiAPI;
  }
}

export {};
