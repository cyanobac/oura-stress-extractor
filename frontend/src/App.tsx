import { useState, useRef, useEffect, useCallback } from "react";
import { extractStress, type ExtractResult, type StressPoint } from "./api";
import { ZONES, ZONE_ORDER } from "./zones";

/* ---------- helpers ---------- */

function hhmm(iso: string): string {
  const t = iso.split("T")[1] ?? iso;
  return t.slice(0, 5);
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function toCsv(result: ExtractResult): string {
  const rows = ["timestamp,zone"];
  for (const p of result.points) rows.push(`${p.timestamp},${p.zone}`);
  return rows.join("\n");
}

function downloadCsv(result: ExtractResult, date: string) {
  const blob = new Blob([toCsv(result)], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `stress_zones_${date || "export"}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/* ---------- small pieces ---------- */

function ThemeToggle() {
  const [theme, setTheme] = useState<"dark" | "light">(() =>
    document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark"
  );

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("theme", theme);
    } catch {
      /* storage unavailable — non-fatal */
    }
  }, [theme]);

  return (
    <button
      type="button"
      className="theme-toggle"
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
    >
      {theme === "dark" ? (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <path
            d="M21 12.8A8.5 8.5 0 1 1 11.2 3a6.6 6.6 0 0 0 9.8 9.8Z"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinejoin="round"
          />
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="4.2" stroke="currentColor" strokeWidth="1.6" />
          <path
            d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
      )}
    </button>
  );
}

function ZoneTag({ zone }: { zone: string }) {
  const z = ZONES[zone] ?? { label: zone, color: "var(--text-mut)" };
  return (
    <span className="ztag" style={{ "--zc": z.color } as React.CSSProperties}>
      <span className="ztag-dot" />
      {z.label}
    </span>
  );
}

/* ---------- upload zone ---------- */

function UploadZone({
  file,
  previewUrl,
  onFile,
  onClear,
}: {
  file: File | null;
  previewUrl: string | null;
  onFile: (f: File) => void;
  onClear: () => void;
}) {
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) onFile(f);
  };

  if (file && previewUrl) {
    return (
      <div className="preview">
        <div className="preview-shot">
          <img src={previewUrl} alt="Uploaded screenshot" />
        </div>
        <div className="preview-meta">
          <div className="preview-name">{file.name}</div>
          <div className="preview-sub">
            {fmtSize(file.size)} · {file.type.replace("image/", "").toUpperCase() || "IMG"}
          </div>
          <div className="preview-actions">
            <button type="button" className="ghost-btn" onClick={() => inputRef.current?.click()}>
              Replace
            </button>
            <button type="button" className="ghost-btn danger" onClick={onClear}>
              Remove
            </button>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept="image/png,image/jpeg"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onFile(f);
            }}
          />
        </div>
      </div>
    );
  }

  return (
    <div
      className={"dropzone" + (drag ? " is-drag" : "")}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
      }}
    >
      <div className="drop-icon">
        <svg width="30" height="30" viewBox="0 0 24 24" fill="none">
          <path
            d="M12 16V5M12 5l-4 4M12 5l4 4"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M5 16v2.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V16"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
      </div>
      <div className="drop-title">Drop your Oura screenshot</div>
      <div className="drop-hint">640 × 1136 · PNG or JPEG · or click to browse</div>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
        }}
      />
    </div>
  );
}

/* ---------- original vs annotated, side by side ---------- */

function ImageCompare({
  previewUrl,
  annotatedPng,
  pointsCount,
}: {
  previewUrl: string;
  annotatedPng?: string;
  pointsCount: number;
}) {
  return (
    <div className="compare">
      <figure className="compare-fig">
        <div className="compare-frame">
          <img src={previewUrl} alt="Original screenshot" />
        </div>
        <figcaption>Original</figcaption>
      </figure>

      <figure className="compare-fig">
        <div className="compare-frame">
          <img
            src={annotatedPng ? `data:image/png;base64,${annotatedPng}` : previewUrl}
            alt="Annotated stress chart"
          />
          <span className="annotated-badge">{pointsCount} pts</span>
        </div>
        <figcaption>Annotated</figcaption>
      </figure>
    </div>
  );
}

/* ---------- results table ---------- */

function ResultsTable({ points }: { points: StressPoint[] }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Zone</th>
          </tr>
        </thead>
        <tbody>
          {points.map((p, i) => (
            <tr key={i}>
              <td className="t-time">{hhmm(p.timestamp)}</td>
              <td>
                <ZoneTag zone={p.zone} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ZoneLegend() {
  return (
    <div className="legend">
      {ZONE_ORDER.map((z) => (
        <span key={z} className="legend-item" style={{ "--zc": ZONES[z].color } as React.CSSProperties}>
          <span className="legend-dot" />
          {ZONES[z].label}
        </span>
      ))}
    </div>
  );
}

/* ---------- main app ---------- */

export function App() {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [date, setDate] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ExtractResult | null>(null);
  const objUrlRef = useRef<string | null>(null);

  const today = new Date().toISOString().split("T")[0];

  const setObjectFile = useCallback((f: File) => {
    if (objUrlRef.current) URL.revokeObjectURL(objUrlRef.current);
    const url = URL.createObjectURL(f);
    objUrlRef.current = url;
    setFile(f);
    setPreviewUrl(url);
    setResult(null);
    setError(null);
  }, []);

  const clearFile = useCallback(() => {
    if (objUrlRef.current) {
      URL.revokeObjectURL(objUrlRef.current);
      objUrlRef.current = null;
    }
    setFile(null);
    setPreviewUrl(null);
    setResult(null);
  }, []);

  // Revoke the last object URL on unmount.
  useEffect(() => {
    return () => {
      if (objUrlRef.current) URL.revokeObjectURL(objUrlRef.current);
    };
  }, []);

  const canSubmit = file !== null && date !== "" && !loading;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !date) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      // Always request the annotated image so the compare view can show it.
      setResult(await extractStress(file, date, true));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const firstT = result ? hhmm(result.meta.first_time) : "";
  const lastT = result ? hhmm(result.meta.last_time) : "";

  return (
    <div className="page">
      <div className="glow" />

      <header className="masthead">
        <div className="brand">
          <span className="brand-tool">Oura Stress Data Extractor</span>
          <ThemeToggle />
        </div>
        <h1>Extract Oura Daytime Stress data from a screenshot.</h1>
        <p className="subtitle">
          Upload a Daytime Stress screenshot and get a clean, downloadable timeline. <br />
          Screenshots are processed in memory and never stored.
        </p>
      </header>

      <form onSubmit={onSubmit} className="card">
        <div className="form-top">
          <div className="field form-col">
            <label className="field-label">Screenshot</label>
            <UploadZone
              file={file}
              previewUrl={previewUrl}
              onFile={setObjectFile}
              onClear={clearFile}
            />
          </div>

          <div className="form-col form-col-right">
            <div className="field date-field">
              <label className="field-label" htmlFor="date">
                Chart date
              </label>
              <input
                id="date"
                type="date"
                className="text-input"
                value={date}
                max={today}
                onChange={(e) => {
                  setDate(e.target.value);
                  setResult(null);
                }}
              />
              <p className="date-hint">The calendar day this stress chart represents.</p>
            </div>

            {result ? (
              <button
                type="button"
                className="submit-btn is-download"
                onClick={() => downloadCsv(result, date)}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M12 4v10m0 0l-3.5-3.5M12 14l3.5-3.5"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d="M5 17v1.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V17"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  />
                </svg>
                Download CSV
              </button>
            ) : (
              <button type="submit" className="submit-btn" disabled={!canSubmit}>
                {loading ? (
                  <span className="btn-loading">
                    Reading chart
                    <span className="dots">
                      <i>.</i>
                      <i>.</i>
                      <i>.</i>
                    </span>
                  </span>
                ) : (
                  "Extract stress zones"
                )}
              </button>
            )}
          </div>
        </div>
      </form>

      {error && <div className="error-banner">⚠ {error}</div>}

      {result && (
        <section className="results">
          <div className="results-header">
            <h2>{result.points.length} data points</h2>
            <p className="results-meta">
              {firstT}–{lastT} · 15-min samples
            </p>
          </div>

          {previewUrl && (
            <ImageCompare
              previewUrl={previewUrl}
              annotatedPng={result.annotated_png}
              pointsCount={result.points.length}
            />
          )}

          <ZoneLegend />
          <ResultsTable points={result.points} />

          {result.warnings.length > 0 && (
            <ul className="warnings">
              {result.warnings.map((w, i) => (
                <li key={i}>
                  <span className="warn-icon">!</span>
                  {w}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
