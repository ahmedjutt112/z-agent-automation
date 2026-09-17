/** Emergency banner — master prompt §11. */

import { useStore } from "../store";

export function EmergencyBanner() {
  const engaged = useStore((s) => s.emergencyEngaged);
  const reset = useStore((s) => s.resetEmergency);

  if (!engaged) return null;

  return (
    <div className="bg-red-600 text-white px-4 py-2 flex items-center justify-between text-sm font-medium">
      <span>
        Emergency stop engaged — all automation paused.
        <span className="ml-2 text-red-200 text-xs">(Ctrl+Shift+Esc)</span>
      </span>
      <button
        onClick={() => {
          reset();
          window.zai?.emergencyStop?.();
        }}
        className="bg-red-800 hover:bg-red-700 px-3 py-1 rounded text-xs uppercase tracking-wider"
      >
        Reset
      </button>
    </div>
  );
}
