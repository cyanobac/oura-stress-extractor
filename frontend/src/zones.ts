// Zone display config. Keys match the backend's zone strings
// (backend/app/extractor/image_helpers.py::ZONES), so ZONES[p.zone] resolves
// directly. Colors reference the oklch CSS variables defined in index.css.

export const ZONE_ORDER = ["restored", "relaxed", "engaged", "stressed"] as const;

export const ZONES: Record<string, { label: string; color: string }> = {
  restored: { label: "Restored", color: "var(--z-restored)" },
  relaxed: { label: "Relaxed", color: "var(--z-relaxed)" },
  engaged: { label: "Engaged", color: "var(--z-engaged)" },
  stressed: { label: "Stressed", color: "var(--z-stressed)" },
};
