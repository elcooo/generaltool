import { useMemo, useState } from "react";
import {
  VerticalTimeline,
  VerticalTimelineElement,
} from "react-vertical-timeline-component";
import "react-vertical-timeline-component/style.min.css";
import type { PlayerReport, TimelineItem } from "./types";

interface Props {
  players: PlayerReport[];
}

const PLAYER_COLORS = ["#0c5f7d", "#7a4a8a", "#c4572d", "#2e8b57", "#b42828", "#a07020"];

interface BucketEntry {
  start: number; // seconds
  perPlayer: { player: PlayerReport; items: TimelineItem[] }[];
}

function formatClock(s: number): string {
  const m = Math.floor(s / 60);
  const ss = s % 60;
  return `${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

function bucketize(players: PlayerReport[], groupSeconds: number): BucketEntry[] {
  const allStarts = new Set<number>();
  const perPlayerBuckets: Map<number, Map<number, TimelineItem[]>> = new Map();

  players.forEach((p) => {
    const m = new Map<number, TimelineItem[]>();
    perPlayerBuckets.set(p.player_number, m);
    for (const item of p.timeline) {
      const sec = Math.floor((item.timecode || 0) / 30);
      const start = Math.floor(sec / groupSeconds) * groupSeconds;
      if (!m.has(start)) m.set(start, []);
      m.get(start)!.push(item);
      allStarts.add(start);
    }
  });

  const sorted = Array.from(allStarts).sort((a, b) => a - b);
  return sorted.map((start) => ({
    start,
    perPlayer: players.map((p) => ({
      player: p,
      items: perPlayerBuckets.get(p.player_number)?.get(start) ?? [],
    })),
  }));
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
          alt={item.action}
          width={28}
          height={28}
          style={{ borderRadius: 5, border: "1px solid #d7ceb9", verticalAlign: "middle" }}
          loading="lazy"
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

export default function Timeline({ players }: Props) {
  const [groupSeconds, setGroupSeconds] = useState(60);
  const [hideMove, setHideMove] = useState(false);

  const visiblePlayers = useMemo(
    () =>
      players.map((p) => ({
        ...p,
        timeline: hideMove ? p.timeline.filter((i) => i.action !== "MoveTo") : p.timeline,
      })),
    [players, hideMove]
  );

  const buckets = useMemo(() => bucketize(visiblePlayers, groupSeconds), [
    visiblePlayers,
    groupSeconds,
  ]);

  if (players.length === 0) return null;

  // Two-player branching layout works best with the lib's left/right alternating
  // mode. For 2 players we force player 0 = left, player 1 = right by using
  // explicit "position" prop. For >2 players fall back to alternating mode.
  const twoPlayer = players.length === 2;

  return (
    <div>
      <div className="toolbar">
        <label>
          Group seconds:
          <input
            type="number"
            min={5}
            max={300}
            step={5}
            value={groupSeconds}
            onChange={(e) => setGroupSeconds(Math.max(5, parseInt(e.target.value || "60", 10) || 60))}
            style={{ width: 70 }}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={hideMove}
            onChange={(e) => setHideMove(e.target.checked)}
          />
          Hide Move actions
        </label>
        <span className="muted">
          {buckets.length} time buckets · {visiblePlayers.reduce((acc, p) => acc + p.timeline.length, 0)} actions
        </span>
      </div>

      <VerticalTimeline lineColor="#cfc7b4" animate={false}>
        {buckets.map((bucket) => {
          const label = `${formatClock(bucket.start)}–${formatClock(bucket.start + groupSeconds - 1)}`;

          if (twoPlayer) {
            // Render one element per player per bucket, side-aligned.
            return (
              <div key={bucket.start}>
                {bucket.perPlayer.map((entry, idx) => {
                  if (entry.items.length === 0) return null;
                  const color = PLAYER_COLORS[idx % PLAYER_COLORS.length];
                  return (
                    <VerticalTimelineElement
                      key={`${bucket.start}-${entry.player.player_number}`}
                      position={idx === 0 ? "left" : "right"}
                      contentStyle={{ background: "#fffdf7", border: "1px solid #ded8cb" }}
                      contentArrowStyle={{ borderRight: "7px solid #fffdf7" }}
                      iconStyle={{ background: color, color: "#fff" }}
                      icon={
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            width: "100%",
                            height: "100%",
                            fontSize: 11,
                            fontWeight: 700,
                          }}
                        >
                          {label}
                        </div>
                      }
                    >
                      <div className="vt-card">
                        <div className="vt-label" style={{ color }}>
                          {entry.player.player_name}
                        </div>
                        <div style={{ marginTop: 6 }}>
                          {entry.items.map((it, i) => (
                            <ItemTile key={i} item={it} />
                          ))}
                        </div>
                      </div>
                    </VerticalTimelineElement>
                  );
                })}
              </div>
            );
          }

          // >2 players: stack each in a single element.
          return (
            <VerticalTimelineElement
              key={bucket.start}
              contentStyle={{ background: "#fffdf7", border: "1px solid #ded8cb" }}
              iconStyle={{ background: "#0c5f7d", color: "#fff" }}
              icon={
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    width: "100%",
                    height: "100%",
                    fontSize: 11,
                    fontWeight: 700,
                  }}
                >
                  {label}
                </div>
              }
            >
              {bucket.perPlayer.map((entry, idx) =>
                entry.items.length === 0 ? null : (
                  <div key={entry.player.player_number} style={{ marginBottom: 8 }}>
                    <div
                      className="vt-label"
                      style={{ color: PLAYER_COLORS[idx % PLAYER_COLORS.length] }}
                    >
                      {entry.player.player_name}
                    </div>
                    <div style={{ marginTop: 4 }}>
                      {entry.items.map((it, i) => (
                        <ItemTile key={i} item={it} />
                      ))}
                    </div>
                  </div>
                )
              )}
            </VerticalTimelineElement>
          );
        })}
      </VerticalTimeline>
    </div>
  );
}
