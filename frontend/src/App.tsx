import { useEffect, useRef, useState } from "react";
import Timeline from "./Timeline";
import type { AnalyzeReport } from "./types";

export default function App() {
  const [report, setReport] = useState<AnalyzeReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load demo on first mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/demo");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json: AnalyzeReport = await res.json();
        if (!cancelled) setReport(json);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function uploadFile(file: File) {
    const data = new FormData();
    data.append("file", file);
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/analyze", { method: "POST", body: data });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const json: AnalyzeReport = await res.json();
      setReport(json);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="report-bare">
      {report && (
        <Timeline
          players={report.players}
          filename={report.filename}
          loading={loading}
          error={error}
          onPickFile={() => fileInputRef.current?.click()}
        />
      )}
      {!report && loading && (
        <div className="vt-loading">Loading demo replay…</div>
      )}
      {!report && !loading && (
        <div className="vt-loading">
          <div>Could not load demo replay.</div>
          {error && <div className="muted" style={{ marginTop: 6 }}>Error: {error}</div>}
          <button
            style={{ marginTop: 12 }}
            onClick={() => fileInputRef.current?.click()}
          >
            Upload a replay
          </button>
        </div>
      )}
      <input
        ref={fileInputRef}
        type="file"
        accept=".rep"
        style={{ display: "none" }}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) uploadFile(f);
          e.currentTarget.value = "";
        }}
      />
    </div>
  );
}
