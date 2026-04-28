import { useState } from "react";
import Timeline from "./Timeline";
import type { AnalyzeReport } from "./types";

export default function App() {
  const [report, setReport] = useState<AnalyzeReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
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
    <div className="wrap">
      <div className="panel">
        <h1>Zero Hour Replay Report</h1>
        <p className="muted">
          <a href="/">← Back to home</a> · React vertical-timeline viewer
        </p>
        {!report && (
          <form onSubmit={onSubmit}>
            <input type="file" name="file" accept=".rep" required />
            <div style={{ marginTop: 10, display: "flex", gap: 10, alignItems: "center" }}>
              <button type="submit" disabled={loading}>
                {loading ? "Analyzing…" : "Analyze Replay"}
              </button>
              {error && <span style={{ color: "#b42828" }}>Error: {error}</span>}
            </div>
          </form>
        )}
        {report && (
          <button
            onClick={() => {
              setReport(null);
              setError(null);
            }}
            style={{ background: "#5d6774" }}
          >
            Upload another replay
          </button>
        )}
      </div>

      {report && (
        <>
          <div className="panel">
            <h2 style={{ margin: "0 0 6px 0" }}>{report.filename}</h2>
            <div className="muted">
              Map: <code>{report.replay.map_file}</code> · Duration:{" "}
              <code>{report.replay.duration_seconds_estimate}s</code> · Total commands:{" "}
              <code>{report.replay.total_actions}</code> · Meaningful:{" "}
              <code>{report.replay.meaningful_actions_total}</code>
            </div>
          </div>

          <div className="panel">
            <h3 style={{ margin: "0 0 8px 0" }}>Players</h3>
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Player</th>
                  <th>Meaningful</th>
                  <th>Eff. APM</th>
                  <th>Macro</th>
                  <th>Micro</th>
                  <th>Eco</th>
                  <th>Top Actions</th>
                </tr>
              </thead>
              <tbody>
                {report.players.map((p) => (
                  <tr key={p.player_number}>
                    <td>{p.player_number}</td>
                    <td>
                      <strong>{p.player_name}</strong>
                    </td>
                    <td>{p.meaningful_actions}</td>
                    <td>{p.effective_apm}</td>
                    <td>{p.macro_actions}</td>
                    <td>{p.micro_actions}</td>
                    <td>{p.economy_actions}</td>
                    <td>
                      {p.top_meaningful_orders
                        .slice(0, 5)
                        .map((o) => `${o.order} (${o.count})`)
                        .join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="panel">
            <h3 style={{ margin: "0 0 8px 0" }}>Action Timeline</h3>
            <Timeline players={report.players} />
          </div>
        </>
      )}
    </div>
  );
}
