/** Settings page — master prompt §72. */

export function Settings() {
  return (
    <div>
      <h1 className="text-2xl font-semibold mb-4">Settings</h1>
      <div className="space-y-3">
        {["General", "AI Models", "Automation", "Browser", "Permissions", "Security",
          "Keyboard Shortcuts", "Voice", "Notifications", "Scheduler", "Storage",
          "Privacy", "Advanced", "Developer"].map((section) => (
          <div key={section} className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 flex items-center justify-between">
            <div>
              <div className="font-medium">{section}</div>
              <div className="text-xs text-zinc-500 mt-0.5">
                {section === "General" ? "Application preferences, language, theme" :
                 section === "AI Models" ? "Provider configuration and default models" :
                 section === "Security" ? "Risk thresholds, kill switch, audit logging" :
                 "Configure " + section.toLowerCase()}
              </div>
            </div>
            <button className="text-xs bg-zinc-800 hover:bg-zinc-700 px-3 py-1.5 rounded">
              Open
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
