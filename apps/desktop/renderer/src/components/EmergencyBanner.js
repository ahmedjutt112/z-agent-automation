import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/** Emergency banner — master prompt §11. */
import { useStore } from "../store";
export function EmergencyBanner() {
    const engaged = useStore((s) => s.emergencyEngaged);
    const reset = useStore((s) => s.resetEmergency);
    if (!engaged)
        return null;
    return (_jsxs("div", { className: "bg-red-600 text-white px-4 py-2 flex items-center justify-between text-sm font-medium", children: [_jsxs("span", { children: ["Emergency stop engaged \u2014 all automation paused.", _jsx("span", { className: "ml-2 text-red-200 text-xs", children: "(Ctrl+Shift+Esc)" })] }), _jsx("button", { onClick: () => {
                    reset();
                    window.zai?.emergencyStop?.();
                }, className: "bg-red-800 hover:bg-red-700 px-3 py-1 rounded text-xs uppercase tracking-wider", children: "Reset" })] }));
}
