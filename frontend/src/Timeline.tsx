import { useMemo, useState } from "react";
import type { PlayerReport, TimelineItem } from "./types";

interface Props {
  players: PlayerReport[];
}

const PLAYER_COLORS = ["#0c5f7d", "#7a4a8a", "#c4572d", "#2e8b57", "#b42828", "#a07020"];

function formatClock(s: number): string {
  const m = Math.floor(s / 60);
  const ss = s % 60;
  return `${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

function ItemTile({ item }: { item: TimelineItem }) {
  const label =
    item.template_name_human ||
    item.template_name ||
    item.upgrade_name_human ||
    item.upgrade_name ||
    item.science_name_human ||
    item.science_name ||
    item.power_name_human ||
    item.power_name ||
    item.label;
  const title = `${item.clock} ${item.label}${label && label !== item.label ? ` · ${label}` : ""}${
    item.detail ? `\n${item.detail}` : ""
  }`;
  return (
    <span title={title} style={{ display: "inline-block", marginRight: 4, marginBottom: 4 }}>
      {item.icon_url ? (
        <img
          src={item.icon_url}
          alt=""
          width={28}
          height={28}
          style={{ borderRadius: 5, border: "1px solid #d7ceb9", verticalAlign: "middle" }}
          loading="lazy"
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = "none";
          }}
        />
      ) : (
        <span
          style={{
            display: "inline-block",
            padding: "2px 6px",
            borderRadius: 5,
            background: "#eee",
            fontSize: 11,
            border: "1px solid #d7ceb9",
          }}
        >
          {item.label}
        </span>
      )}
    </span>
  );
}

interface Row {
  second: number; // unique time slot key
  perPlayer: TimelineItem[][]; // index aligned with players[]
}

function buildRows(players: PlayerReport[], hideMove: boolean): Row[] {
  const rowMap = new Map<number, TimelineItem[][]>();
  players.forEach((p, idx) => {
    p.timeline.forEach((it) => {
      if (hideMove && it.action === "MoveTo") return;
      const sec = Math.floor((it.timecode || 0) / 30);
      if (!rowMap.has(sec)) rowMap.set(sec, players.map(() => []));
      rowMap.get(sec)![idx].push(it);
    });
  });
  return Array.from(rowMap.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([second, perPlayer]) => ({ second, perPlayer }));
}

export default function Timeline({ players }: Props) {
  const [hideMove, setHideMove] = useState(false);

  const rows = useMemo(() => buildRows(players, hideMove), [players, hideMove]);

  if (players.length === 0) return null;

  const twoPlayer = players.length === 2;
  const totalActions = rows.reduce(
    (acc, r) => acc + r.perPlayer.reduce((a, items) => a + items.length, 0),
    0
  );

  return (
    <div>
      <div className="toolbar">
        <label>
          <input
            type="checkbox"
            checked={hideMove}
            onChange={(e) => setHideMove(e.target.checked)}
          />
          Hide Move actions
        </label>
        <span className="muted">
          {rows.length} time slots · {totalActions} actions
        </span>
      </div>

      <div className="vt-spine-wrap">
        <div className="vt-spine-line" />
        <div className="vt-rows">
          {rows.map((row) => {
            const maxItems = Math.max(1, ...row.perPlayer.map((arr) => arr.length));
            return (
              <div
                key={row.second}
                className="vt-row"
                style={{ minHeight: maxItems * 36 + 16 }}
              >
                {twoPlayer ? (
                  <>
                    <div className="vt-side vt-left">
                      {row.perPlayer[0].length > 0 && (
                        <div
                          className="vt-card"
                          style={{ borderColor: PLAYER_COLORS[0] }}
                        >
                          {row.perPlayer[0].map((it, i) => (
                            <ItemTile key={i} item={it} />
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="vt-axis">
                      <div className="vt-dot" />
                      <div className="vt-tick">{formatClock(row.second)}</div>
                    </div>
                    <div className="vt-side vt-right">
                      {row.perPlayer[1].length > 0 && (
                        <div
                          className="vt-card"
                          style={{ borderColor: PLAYER_COLORS[1] }}
                        >
                          {row.perPlayer[1].map((it, i) => (
                            <ItemTile key={i} item={it} />
                          ))}
                        </div>
                      )}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="vt-side vt-left" />
                    <div className="vt-axis">
                      <div className="vt-dot" />
                      <div className="vt-tick">{formatClock(row.second)}</div>
                    </div>
                    <div className="vt-side vt-right">
                      <div className="vt-card">
                        {row.perPlayer.map((items, idx) =>
                          items.length === 0 ? null : (
                            <div key={idx} style={{ marginBottom: 4 }}>
                              <span
                                className="vt-label"
                                style={{ color: PLAYER_COLORS[idx % PLAYER_COLORS.length] }}
                              >
                                {players[idx].player_name}:
                              </span>{" "}
                              {items.map((it, i) => (
                                <ItemTile key={i} item={it} />
                              ))}
                            </div>
                          )
                        )}
                      </div>
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
