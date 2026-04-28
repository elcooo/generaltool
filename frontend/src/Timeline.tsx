import { useMemo, useRef, useState } from "react";
import type { PlayerReport, TimelineItem } from "./types";
import { getActionIcon } from "./actionIcons";

interface Props {
  players: PlayerReport[];
  filename?: string;
  loading?: boolean;
  error?: string | null;
  onPickFile?: () => void;
}

const PLAYER_COLORS = ["#58a6ff", "#d29922", "#bc8cff", "#3fb950", "#ff7b72", "#79c0ff"];

function formatClock(s: number): string {
  const m = Math.floor(s / 60);
  const ss = s % 60;
  return `${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

function ItemTile({ item }: { item: TimelineItem }) {
  const subject =
    item.template_name_human ||
    item.template_name ||
    item.upgrade_name_human ||
    item.upgrade_name ||
    item.science_name_human ||
    item.science_name ||
    item.power_name_human ||
    item.power_name;

  const isGameAsset = item.icon_url && !item.icon_url.includes("/icons/actions/");

  let inner: React.ReactNode;
  if (isGameAsset) {
    inner = (
      <img
        src={item.icon_url!}
        alt=""
        width={26}
        height={26}
        loading="lazy"
        onError={(e) => {
          (e.currentTarget as HTMLImageElement).style.display = "none";
        }}
      />
    );
  } else {
    const spec = getActionIcon(item.action);
    if (spec && "Icon" in spec) {
      const { Icon, bg, fg } = spec;
      inner = (
        <span className="vt-action" style={{ background: bg, color: fg }}>
          <Icon size={16} strokeWidth={2.5} />
        </span>
      );
    } else if (spec && "number" in spec) {
      inner = (
        <span
          className="vt-action vt-action-num"
          style={{ background: spec.bg, color: spec.fg }}
        >
          {spec.number}
        </span>
      );
    } else {
      inner = <span className="vt-fallback">{item.label}</span>;
    }
  }

  return (
    <span className="vt-tile" style={{ display: "block", lineHeight: 0 }}>
      {inner}
      <span className="vt-tooltip" role="tooltip">
        <span className="vt-tooltip-time">{item.clock}</span>
        <span className="vt-tooltip-action">{item.label}</span>
        {subject && <span className="vt-tooltip-subject">{subject}</span>}
        {item.detail && <span className="vt-tooltip-detail">{item.detail}</span>}
      </span>
    </span>
  );
}

interface Row {
  second: number;
  perPlayer: TimelineItem[][];
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

export default function Timeline({ players, filename, loading, error, onPickFile }: Props) {
  const [hideMove, setHideMove] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const rows = useMemo(() => buildRows(players, hideMove), [players, hideMove]);

  if (players.length === 0) return null;

  const twoPlayer = players.length === 2;
  const totalActions = rows.reduce(
    (acc, r) => acc + r.perPlayer.reduce((a, items) => a + items.length, 0),
    0
  );

  function scrollBy(delta: number) {
    scrollRef.current?.scrollBy({ left: delta, behavior: "smooth" });
  }

  // Map wheel-vertical → horizontal scroll for nicer UX.
  function onWheel(e: React.WheelEvent<HTMLDivElement>) {
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      scrollRef.current?.scrollBy({ left: e.deltaY, behavior: "auto" });
      e.preventDefault();
    }
  }

  return (
    <>
      <div className="vt-options">
        <div className="vt-filename" title={filename}>
          {filename || "Replay"}
        </div>
        {twoPlayer && (
          <div className="vt-players">
            <span className="vt-player-chip" style={{ background: PLAYER_COLORS[0] }}>
              ▲ {players[0].player_name}
            </span>
            <span className="vt-player-chip" style={{ background: PLAYER_COLORS[1] }}>
              ▼ {players[1].player_name}
            </span>
          </div>
        )}
        <label>
          <input
            type="checkbox"
            checked={hideMove}
            onChange={(e) => setHideMove(e.target.checked)}
          />
          Hide Move actions
        </label>
        <span className="muted">
          {rows.length} slots · {totalActions} actions
        </span>
        {onPickFile && (
          <button onClick={onPickFile} disabled={loading}>
            {loading ? "Loading…" : "Upload replay"}
          </button>
        )}
        {error && <div className="vt-error">{error}</div>}
      </div>

      <div className="vt-scroll-buttons">
        <button onClick={() => scrollBy(-600)} aria-label="Scroll left">←</button>
        <button onClick={() => scrollBy(600)} aria-label="Scroll right">→</button>
      </div>

      <div className="vt-h-wrap" ref={scrollRef} onWheel={onWheel}>
        <div className="vt-h-cols">
          {rows.map((row) => {
            const top = twoPlayer ? row.perPlayer[0] : row.perPlayer.flat();
            const bottom = twoPlayer ? row.perPlayer[1] : [];
            return (
              <div key={row.second} className="vt-h-col">
                <div className="vt-h-top">
                  {top.map((it, i) => (
                    <ItemTile key={i} item={it} />
                  ))}
                </div>
                <div className="vt-h-axis">
                  <div className="vt-dot" />
                  <div className="vt-tick">{formatClock(row.second)}</div>
                </div>
                <div className="vt-h-bottom">
                  {bottom.map((it, i) => (
                    <ItemTile key={i} item={it} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
