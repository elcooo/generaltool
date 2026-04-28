from __future__ import annotations

import html
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from replay_tool.analyzer import (
    ReplayParseError,
    analyze_replay_bytes,
    parse_replay_bytes,
    parse_replay_preview_bytes,
)
from replay_tool.icon_provider import (
    get_action_icon_data_uri,
    get_power_icon_data_uri,
    get_science_icon_data_uri,
    get_template_icon_data_uri,
    get_upgrade_icon_data_uri,
)
from replay_tool.importers import import_generals_online_replays


app = FastAPI(title="Zero Hour Replay Analyzer")
_LIBRARY_CACHE: dict[str, dict[str, Any]] = {}
_REPLAY_VALIDITY_CACHE: dict[str, dict[str, Any]] = {}

_ICONS_DIR = Path(__file__).parent / "icons"
if _ICONS_DIR.exists():
    app.mount("/icons", StaticFiles(directory=str(_ICONS_DIR)), name="icons")

_FRONTEND_DIST = Path(__file__).parent / "static"
if _FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")


ARMY_BY_FACTION = {
    0: "USA",
    1: "China",
    2: "GLA",
    3: "USA Laser",
    4: "USA Air Force",
    5: "USA Super Weapon",
    6: "China Tank",
    7: "China Nuke",
    8: "China Infantry",
    9: "GLA Toxin",
    10: "GLA Demo",
    11: "GLA Stealth",
    12: "Random",
}


def _army_name(faction: int | None) -> str:
    if faction is None:
        return "Unknown"
    return ARMY_BY_FACTION.get(int(faction), f"Faction {faction}")


def _fmt_utc(unix_ts: int) -> str:
    if unix_ts <= 0:
        return "Unknown"
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse_datetime_filter(value: str) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        # Supports HTML datetime-local (YYYY-MM-DDTHH:MM) and ISO input.
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp())


def _library_cache_key(root_path: Path, max_files: int) -> str:
    return f"{root_path.resolve()}::{max_files}"


def _build_library_index(root_path: Path, max_files: int) -> dict[str, Any]:
    files: list[Path] = []
    if root_path.exists() and root_path.is_dir():
        files = sorted(root_path.rglob("*.rep"), key=lambda p: p.as_posix())[:max_files]
    entries: list[dict[str, Any]] = []
    parse_errors = 0

    for rep in files:
        try:
            # Fast path: preview parsing usually only needs the header area.
            # Fallback to full file read only when needed.
            with rep.open("rb") as fh:
                payload = fh.read(131072)
            try:
                header, metadata = parse_replay_preview_bytes(payload)
            except ReplayParseError:
                header, metadata = parse_replay_preview_bytes(rep.read_bytes())
        except Exception:
            parse_errors += 1
            continue
        slots = metadata.get("slots") or []
        human_slots = []
        for slot in slots:
            if slot.get("slot_type") != "human":
                continue
            name = str(slot.get("name") or "Unknown")
            faction = slot.get("faction")
            army_name = _army_name(faction)
            human_slots.append(
                {
                    "name": name,
                    "name_l": name.lower(),
                    "army": army_name,
                    "army_l": army_name.lower(),
                }
            )
        entries.append(
            {
                "path": str(rep),
                "map_file": str(metadata.get("map_file") or "Unknown"),
                "map_l": str(metadata.get("map_file") or "Unknown").lower(),
                "start_time_unix": int(header.start_time_unix),
                "humans": human_slots,
            }
        )

    player_names = sorted(
        {
            h["name"]
            for e in entries
            for h in e.get("humans", [])
            if h.get("name")
        },
        key=lambda s: s.lower(),
    )
    map_names = sorted(
        {
            e["map_file"]
            for e in entries
            if e.get("map_file")
        },
        key=lambda s: s.lower(),
    )
    army_names = sorted(
        {
            h["army"]
            for e in entries
            for h in e.get("humans", [])
            if h.get("army")
        },
        key=lambda s: s.lower(),
    )
    return {
        "entries": entries,
        "player_names": player_names,
        "map_names": map_names,
        "army_names": army_names,
        "scanned": len(files),
        "parse_errors": parse_errors,
    }


def _is_replay_playable(path: Path) -> tuple[bool, str]:
    cache_key = str(path.resolve())
    try:
        stat = path.stat()
    except Exception as exc:
        return False, f"stat failed: {exc}"

    signature = (int(stat.st_mtime_ns), int(stat.st_size))
    cached = _REPLAY_VALIDITY_CACHE.get(cache_key)
    if cached and tuple(cached.get("sig", ())) == signature:
        return bool(cached.get("ok", False)), str(cached.get("reason", ""))

    if stat.st_size <= 0:
        result = (False, "empty file")
    else:
        try:
            parse_replay_bytes(path.read_bytes())
            result = (True, "")
        except ReplayParseError as exc:
            result = (False, str(exc))
        except Exception as exc:
            result = (False, f"parse failed: {exc}")

    _REPLAY_VALIDITY_CACHE[cache_key] = {
        "sig": signature,
        "ok": result[0],
        "reason": result[1],
    }
    return result


def _get_library_index(root_path: Path, max_files: int, refresh: bool) -> dict[str, Any]:
    key = _library_cache_key(root_path, max_files)
    if refresh or key not in _LIBRARY_CACHE:
        _LIBRARY_CACHE[key] = _build_library_index(root_path, max_files)
    return _LIBRARY_CACHE[key]


def _player_match_score(query: str, name_l: str) -> int:
    if not query:
        return 1
    if name_l == query:
        return 400
    if name_l.startswith(query):
        return 300
    if query in name_l:
        return 200
    tokens = [t for t in query.split() if t]
    if tokens and all(t in name_l for t in tokens):
        return 120
    return 0


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Zero Hour Replay Analyzer</title>
    <style>
      :root {
        --bg: #ecebe6;
        --panel: #fdfbf6;
        --line: #d8d2c6;
        --text: #1d232b;
        --muted: #5d6774;
        --accent: #0c5f7d;
      }
      body {
        margin: 0;
        font-family: "Bahnschrift", "Segoe UI Variable", "Trebuchet MS", sans-serif;
        background:
          radial-gradient(circle at 8% 0%, #d7e9e4 0%, transparent 36%),
          radial-gradient(circle at 90% 0%, #ece1cf 0%, transparent 32%),
          var(--bg);
        color: var(--text);
      }
      .wrap {
        max-width: 980px;
        margin: 28px auto;
        padding: 0 16px;
      }
      .panel {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 18px;
        box-shadow: 0 10px 30px rgba(21, 35, 48, 0.08);
      }
      h1 {
        margin: 0 0 8px 0;
        font-size: 2rem;
        letter-spacing: 0.3px;
      }
      p {
        margin: 8px 0;
        color: var(--muted);
      }
      .grid {
        display: grid;
        gap: 10px;
        grid-template-columns: 1fr 1fr;
      }
      .section {
        margin-top: 14px;
        padding-top: 10px;
        border-top: 1px solid #e4decf;
      }
      input {
        width: 100%;
        box-sizing: border-box;
        border: 1px solid var(--line);
        border-radius: 9px;
        padding: 9px 10px;
        background: #fff;
      }
      button {
        border: 0;
        border-radius: 10px;
        background: linear-gradient(120deg, var(--accent), #0b6a76);
        color: white;
        padding: 10px 14px;
        cursor: pointer;
        font-weight: 600;
      }
      .actions {
        margin-top: 10px;
        display: flex;
        gap: 10px;
        align-items: center;
      }
      .hint {
        font-size: 12px;
        color: #6a7584;
      }
      @media (max-width: 760px) {
        .grid {
          grid-template-columns: 1fr;
        }
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="panel">
        <h1>Zero Hour Replay Analyzer</h1>
        <p>Analyze <code>.rep</code> files, browse replay libraries, and import from GeneralsOnline.</p>
        <form action="/analyze" method="post" enctype="multipart/form-data">
          <input type="file" name="file" accept=".rep" required />
          <div class="actions">
            <button type="submit">Analyze Replay</button>
            <a href="/report" style="text-decoration:none;">
              <button type="button" style="background:linear-gradient(120deg,#3a8266,#266f59);">Open New Report (Beta)</button>
            </a>
            <span class="hint">Beta opens the React vertical-timeline viewer.</span>
          </div>
        </form>
        <div class="section">
        <p><strong>Match Library</strong>: search by player, map, and army, with unplayable replay filtering.</p>
        <form action="/library" method="get">
          <div class="grid">
            <input type="text" name="root" placeholder="Replay folder path (e.g. refs/GeneralsReplays/GeneralsZH/1.04/Replays)" />
            <input type="text" name="player" placeholder="Player name contains..." />
            <input type="text" name="map" placeholder="Map contains..." />
            <input type="text" name="army" placeholder="Army contains... (e.g. USA, GLA Stealth)" />
          </div>
          <input type="hidden" name="show_unplayable" value="0" />
          <div class="actions">
            <button type="submit">Search Match Library</button>
            <span class="hint">Default: hide unplayable files</span>
          </div>
        </form>
        </div>
        <div class="section">
        <p><strong>Import from Internet (GeneralsOnline)</strong></p>
        <form action="/import/generalsonline" method="post">
          <div class="grid">
            <input type="text" name="output_dir" value="imports/generalsonline" placeholder="Output folder path" />
            <input type="number" name="max_matches" min="1" max="200" value="30" />
            <input type="text" name="player" placeholder="Player contains..." />
            <input type="text" name="map" placeholder="Map contains..." />
            <input type="text" name="army" placeholder="Army contains... (e.g. gla_demo, china_nuke)" />
          </div>
          <div class="actions">
            <label style="display:inline-flex; align-items:center; gap:6px;">
              <input type="checkbox" name="debug" value="1" />
              Debug mode
            </label>
          </div>
          <div class="actions">
            <button type="submit">Import Replays</button>
            <span class="hint">Downloads only valid replays</span>
          </div>
        </form>
        </div>
      </div>
    </div>
  </body>
</html>
"""


@app.get("/library", response_class=HTMLResponse)
def library(
    root: str = Query(default=""),
    player: str = Query(default=""),
    map: str = Query(default=""),
    army: str = Query(default=""),
    start_from: str = Query(default=""),
    start_to: str = Query(default=""),
    show_unplayable: int = Query(default=0),
    max_files: int = Query(default=2000, ge=1, le=20000),
    refresh: int = Query(default=0),
) -> str:
    root_path = Path(root).expanduser() if root.strip() else (Path.cwd() / "refs" / "GeneralsReplays")
    player_q = player.strip().lower()
    map_q = map.strip().lower()
    army_q = army.strip().lower()
    start_from_ts = _parse_datetime_filter(start_from)
    start_to_ts = _parse_datetime_filter(start_to)

    rows: list[str] = []
    scanned = 0
    parse_errors = 0
    matched_filters = 0
    shown = 0
    hidden_unplayable = 0
    index = _get_library_index(root_path=root_path, max_files=max_files, refresh=bool(refresh))
    scanned = int(index.get("scanned", 0))
    parse_errors = int(index.get("parse_errors", 0))
    candidate_rows: list[dict[str, Any]] = []

    for e in index.get("entries", []):
        start_time_unix = int(e.get("start_time_unix", 0))
        if start_from_ts is not None and start_time_unix < start_from_ts:
            continue
        if start_to_ts is not None and start_time_unix > start_to_ts:
            continue
        map_file = str(e.get("map_file") or "Unknown")
        if map_q and map_q not in str(e.get("map_l", "")).lower():
            continue
        human_slots = list(e.get("humans") or [])
        if not human_slots:
            continue

        matched = []
        best_score = 0
        for s in human_slots:
            score = _player_match_score(player_q, str(s.get("name_l", "")))
            if score > 0:
                matched.append(s)
                best_score = max(best_score, score)
        if player_q and not matched:
            continue
        if not player_q:
            matched = human_slots
            best_score = 1

        if army_q and not any(army_q in str(s.get("army_l", "")) for s in matched):
            continue

        matched_filters += 1
        rep = Path(str(e.get("path", "")))
        playable, reason = _is_replay_playable(rep)
        if not show_unplayable and not playable:
            hidden_unplayable += 1
            continue
        shown += 1
        rel_path = rep.relative_to(root_path) if rep.is_relative_to(root_path) else rep
        matched_players = ", ".join(f"{s['name']} ({s['army']})" for s in matched)
        all_players = ", ".join(f"{s['name']} ({s['army']})" for s in human_slots) or "No human players"
        status_html = (
            "<span style=\"color:#1c7c3f; font-weight:600;\">Playable</span>"
            if playable
            else f"<span style=\"color:#b03a2e; font-weight:600;\">Unplayable</span><br/><code>{html.escape(reason[:140])}</code>"
        )
        analyze_html = (
            f"<a href=\"/analyze/local?path={quote(str(rep))}\">Analyze</a>"
            if playable
            else "<span style=\"color:#8a8a8a;\">Unavailable</span>"
        )
        candidate_rows.append(
            {
                "score": best_score,
                "start_time_unix": start_time_unix,
                "html": (
                    "<tr>"
                    f"<td><code>{html.escape(str(rel_path))}</code></td>"
                    f"<td>{html.escape(_fmt_utc(start_time_unix))}</td>"
                    f"<td>{html.escape(map_file)}</td>"
                    f"<td>{html.escape(matched_players)}</td>"
                    f"<td>{html.escape(all_players)}</td>"
                    f"<td>{status_html}</td>"
                    f"<td>{analyze_html}</td>"
                    "</tr>"
                ),
            }
        )

    candidate_rows.sort(key=lambda x: (int(x["score"]), int(x["start_time_unix"])), reverse=True)
    rows = [str(x["html"]) for x in candidate_rows]

    rows_html = "".join(rows) or (
        "<tr><td colspan=\"7\">No matches found for current filters.</td></tr>"
    )
    root_val = html.escape(root)
    player_val = html.escape(player)
    map_val = html.escape(map)
    army_val = html.escape(army)
    start_from_val = html.escape(start_from)
    start_to_val = html.escape(start_to)
    visibility_options = (
        "<option value=\"0\" selected>Hide unplayable</option><option value=\"1\">Show all</option>"
        if not show_unplayable
        else "<option value=\"0\">Hide unplayable</option><option value=\"1\" selected>Show all</option>"
    )
    refresh_checked = "checked" if refresh else ""
    army_datalist = "".join(
        f"<option value=\"{html.escape(a)}\"></option>" for a in list(index.get("army_names", []))
    )
    map_datalist = "".join(
        f"<option value=\"{html.escape(m)}\"></option>" for m in list(index.get("map_names", []))[:1000]
    )
    player_datalist = "".join(
        f"<option value=\"{html.escape(p)}\"></option>" for p in list(index.get("player_names", []))[:2000]
    )

    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Replay Match Library</title>
    <style>
      :root {{
        --bg: #f1efe8;
        --paper: #fcfaf5;
        --ink: #1d232b;
        --line: #d8d1c4;
        --accent: #0c5f7d;
      }}
      body {{ font-family: "Bahnschrift", "Segoe UI Variable", "Trebuchet MS", sans-serif; background: radial-gradient(circle at 8% 0%, #dcece8 0%, var(--bg) 42%); color: var(--ink); margin: 0; }}
      .wrap {{ max-width: 1180px; margin: 24px auto; padding: 0 16px; }}
      a {{ color: var(--accent); }}
      .card {{ background: var(--paper); border: 1px solid var(--line); border-radius: 14px; padding: 14px; margin-bottom: 14px; box-shadow: 0 8px 24px rgba(22, 35, 52, 0.06); }}
      table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
      th, td {{ border-bottom: 1px solid #e7e1d4; padding: 9px; text-align: left; vertical-align: top; }}
      th {{ background: #efe8d9; }}
      .grid {{ display:grid; gap:10px; grid-template-columns: 1.8fr 1fr 1fr 1fr 1fr 1fr 110px; }}
      input, button {{ padding: 9px 10px; border: 1px solid var(--line); border-radius: 9px; background: #fff; }}
      button {{ border: 0; background: var(--accent); color: #fff; cursor: pointer; font-weight: 600; }}
      code {{ font-size: 12px; }}
      .toggles {{ display:flex; flex-wrap: wrap; gap: 12px; margin-top: 10px; }}
      @media (max-width: 960px) {{
        .grid {{ grid-template-columns: 1fr; }}
      }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <p><a href="/">Back to Analyzer</a></p>
      <h2>Match Library</h2>
      <div class="card">
        <form method="get" action="/library">
          <div class="grid">
            <input type="text" name="root" placeholder="Replay folder path" value="{root_val}" />
            <input type="text" name="player" list="player-list" placeholder="Player contains..." value="{player_val}" />
            <input type="text" name="map" list="map-list" placeholder="Map contains..." value="{map_val}" />
            <input type="text" name="army" list="army-list" placeholder="Army contains..." value="{army_val}" />
            <input type="datetime-local" name="start_from" value="{start_from_val}" title="Game start from (UTC)" />
            <input type="datetime-local" name="start_to" value="{start_to_val}" title="Game start to (UTC)" />
            <button type="submit">Filter</button>
          </div>
          <div class="toggles">
            <label style="display:inline-flex; align-items:center; gap:6px;">
              Replay visibility:
              <select name="show_unplayable" style="padding:6px 8px; border-radius:8px; border:1px solid #d7cfbf;">
                {visibility_options}
              </select>
            </label>
            <label style="display:inline-flex; align-items:center; gap:6px;">
              <input type="checkbox" name="refresh" value="1" {refresh_checked} />
              Rebuild index (refresh cache)
            </label>
          </div>
          <input type="hidden" name="max_files" value="{max_files}" />
          <datalist id="player-list">{player_datalist}</datalist>
          <datalist id="army-list">{army_datalist}</datalist>
          <datalist id="map-list">{map_datalist}</datalist>
        </form>
      </div>
      <div class="card">
        <strong>Results</strong>
        <p>Scanned: <code>{scanned}</code> | Matched filters: <code>{matched_filters}</code> | Showing: <code>{shown}</code> | Hidden unplayable: <code>{hidden_unplayable}</code> | Parse errors: <code>{parse_errors}</code> | Timezone: <code>UTC</code></p>
        <table>
          <thead>
            <tr>
              <th>Replay File</th>
              <th>Start Time</th>
              <th>Map</th>
              <th>Matched Player(s)</th>
              <th>All Human Players</th>
              <th>Status</th>
              <th>Analyze</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
      </div>
    </div>
  </body>
</html>
"""


@app.post("/import/generalsonline", response_class=HTMLResponse)
def import_generalsonline(
    output_dir: str = Form(default="imports/generalsonline"),
    player: str = Form(default=""),
    map: str = Form(default=""),
    army: str = Form(default=""),
    max_matches: int = Form(default=30, ge=1, le=200),
    debug: int = Form(default=0),
) -> str:
    try:
        report = import_generals_online_replays(
            output_dir=output_dir,
            player_filter=player,
            map_filter=map,
            army_filter=army,
            max_matches=max_matches,
            debug=bool(debug),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Import failed: {exc}") from exc

    rows = report.get("rows", [])
    failure_buckets: dict[str, int] = {}
    row_html = ""
    for row in rows:
        status = str(row.get("status", ""))
        color = "#2e7d32" if status == "downloaded" else ("#8c6d1f" if status == "exists" else "#a5261f")
        mode = str(row.get("validation_mode", "")) or "-"
        saved_path = str(row.get("saved_path", ""))
        players_text = str(row.get("players", ""))
        players_parts = [p.strip() for p in players_text.split(",") if p.strip()]
        if len(players_parts) > 4:
            players_short = ", ".join(players_parts[:4]) + f", +{len(players_parts) - 4} more"
        else:
            players_short = players_text
        raw_error_text = str(row.get("error", ""))
        error_text = raw_error_text
        attempts = row.get("debug_attempts", [])
        attempts_txt = ""
        if isinstance(attempts, list) and attempts:
            parts = []
            for a in attempts[:4]:
                if not isinstance(a, dict):
                    continue
                parts.append(
                    f"[{a.get('result', '')}] {a.get('url', '')} {a.get('error', '')}".strip()
                )
            if parts:
                attempts_txt = " | ".join(parts)
                error_text = f"{error_text} || attempts: {attempts_txt}" if error_text else f"attempts: {attempts_txt}"
        if status == "error":
            bucket = raw_error_text.split(";", 1)[0].strip()[:110] or "Unknown error"
            failure_buckets[bucket] = failure_buckets.get(bucket, 0) + 1
        analyze_cell = (
            f"<a href=\"/analyze/local?path={quote(saved_path)}\">Analyze</a>"
            if saved_path and status in {"downloaded", "exists"} else ""
        )
        row_html += (
            "<tr>"
            f"<td>{row.get('match_id', '')}</td>"
            f"<td><code style=\"color:{color};\">{html.escape(status)}</code></td>"
            f"<td>{html.escape(str(row.get('map_name', '')))}</td>"
            f"<td title=\"{html.escape(players_text)}\">{html.escape(players_short)}</td>"
            f"<td><code>{html.escape(mode)}</code></td>"
            f"<td><code class=\"path-cell\" title=\"{html.escape(saved_path)}\">{html.escape(saved_path)}</code></td>"
            f"<td><code class=\"error-cell\" title=\"{html.escape(error_text)}\">{html.escape(error_text)}</code></td>"
            f"<td>{analyze_cell}</td>"
            "</tr>"
        )
    if not row_html:
        row_html = "<tr><td colspan=\"8\">No rows to display.</td></tr>"

    failure_rows = "".join(
        f"<tr><td>{html.escape(reason)}</td><td>{count}</td></tr>"
        for reason, count in sorted(failure_buckets.items(), key=lambda x: x[1], reverse=True)[:8]
    ) or "<tr><td colspan=\"2\">No failures.</td></tr>"
    debug_events = report.get("debug_events", [])
    debug_json = html.escape(json.dumps(debug_events, indent=2)) if debug_events else ""
    debug_block = (
        "<div class=\"card\">"
        "<strong>Debug Events</strong>"
        "<p>Importer trace (match page, link attempts, validation mode, and errors).</p>"
        f"<pre>{debug_json}</pre>"
        "</div>"
        if debug_events
        else ""
    )

    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>GeneralsOnline Import Report</title>
    <style>
      :root {{
        --bg: #f1efe8;
        --paper: #fcfaf5;
        --ink: #1d232b;
        --line: #d8d1c4;
        --accent: #0c5f7d;
      }}
      body {{ font-family: "Bahnschrift", "Segoe UI Variable", "Trebuchet MS", sans-serif; background: radial-gradient(circle at 8% 0%, #dcece8 0%, var(--bg) 42%); color: var(--ink); margin: 0; }}
      .wrap {{ max-width: 1220px; margin: 24px auto; padding: 0 16px; }}
      a {{ color: var(--accent); }}
      .card {{ background: var(--paper); border: 1px solid var(--line); border-radius: 14px; padding: 14px; margin-bottom: 14px; box-shadow: 0 8px 24px rgba(22, 35, 52, 0.06); }}
      .stats {{ display: grid; grid-template-columns: repeat(3, minmax(150px, 1fr)); gap: 8px; }}
      .stat {{ background: #fff; border: 1px solid #e6dece; border-radius: 10px; padding: 8px 10px; }}
      .stat code {{ font-size: 16px; font-weight: 700; }}
      table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
      th, td {{ border-bottom: 1px solid #e8e1d2; padding: 8px; text-align: left; vertical-align: top; }}
      th {{ background: #efe8d9; position: sticky; top: 0; z-index: 1; }}
      code {{ font-size: 12px; word-break: break-word; }}
      .table-wrap {{ overflow: auto; border: 1px solid #e6dece; border-radius: 10px; }}
      .rows-table {{ table-layout: fixed; min-width: 1400px; }}
      .rows-table th:nth-child(1), .rows-table td:nth-child(1) {{ width: 90px; }}
      .rows-table th:nth-child(2), .rows-table td:nth-child(2) {{ width: 80px; }}
      .rows-table th:nth-child(3), .rows-table td:nth-child(3) {{ width: 170px; }}
      .rows-table th:nth-child(4), .rows-table td:nth-child(4) {{ width: 420px; }}
      .rows-table th:nth-child(5), .rows-table td:nth-child(5) {{ width: 80px; }}
      .rows-table th:nth-child(6), .rows-table td:nth-child(6) {{ width: 340px; }}
      .rows-table th:nth-child(7), .rows-table td:nth-child(7) {{ width: 320px; }}
      .rows-table th:nth-child(8), .rows-table td:nth-child(8) {{ width: 90px; }}
      .path-cell {{
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        display: inline-block;
        max-width: 320px;
      }}
      .error-cell {{
        white-space: normal;
        word-break: break-word;
      }}
      .status-badge {{ font-weight: 700; }}
      pre {{ white-space: pre-wrap; background: #11171f; color: #d4deea; border-radius: 10px; padding: 12px; overflow:auto; }}
      @media (max-width: 900px) {{
        .stats {{ grid-template-columns: repeat(2, minmax(140px, 1fr)); }}
      }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <p><a href="/">Back to Analyzer</a> | <a href="/library?root={html.escape(str(report.get('output_dir', '')))}">Open Imported Folder in Match Library</a></p>
      <h2>GeneralsOnline Import Report</h2>
      <div class="card">
        <p>Output folder: <code>{html.escape(str(report.get('output_dir', '')))}</code></p>
        <div class="stats">
          <div class="stat">Scanned matches<br/><code>{report.get('scanned_matches')}</code></div>
          <div class="stat">Matched filters<br/><code>{report.get('matched_filters')}</code></div>
          <div class="stat">Downloaded<br/><code>{report.get('downloaded')}</code></div>
          <div class="stat">Existing<br/><code>{report.get('skipped_existing')}</code></div>
          <div class="stat">Failed<br/><code>{report.get('failed')}</code></div>
          <div class="stat">Search backend<br/><code>{html.escape(str(report.get('search_backend', 'unknown')))}</code></div>
        </div>
      </div>
      <div class="card">
        <strong>Top failure reasons</strong>
        <table class="rows-table">
          <thead><tr><th>Reason</th><th>Count</th></tr></thead>
          <tbody>{failure_rows}</tbody>
        </table>
      </div>
      {debug_block}
      <div class="card">
        <strong>Rows</strong>
        <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Match ID</th>
              <th>Status</th>
              <th>Map</th>
              <th>Players</th>
              <th>Validation</th>
              <th>Saved Path</th>
              <th>Error</th>
              <th>Analyze</th>
            </tr>
          </thead>
          <tbody>{row_html}</tbody>
        </table>
        </div>
      </div>
    </div>
  </body>
</html>
"""


@app.get("/analyze/local", response_class=HTMLResponse)
async def analyze_local(path: str = Query(...)) -> str:
    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="Replay file not found.")
    if p.suffix.lower() != ".rep":
        raise HTTPException(status_code=400, detail="Only .rep files are supported.")
    if p.stat().st_size == 0:
        raise HTTPException(status_code=400, detail="Replay file is empty.")

    upload_like = UploadFile(filename=p.name, file=io.BytesIO(p.read_bytes()))
    try:
        return await analyze(upload_like)
    except HTTPException as exc:
        detail = html.escape(str(exc.detail))
        return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Replay Load Error</title>
    <style>
      body {{ font-family: "Segoe UI", Tahoma, sans-serif; background: #f6f3ec; margin: 0; }}
      .wrap {{ max-width: 900px; margin: 24px auto; padding: 0 20px; }}
      .card {{ background: #fffdf7; border: 1px solid #ded8cb; border-radius: 12px; padding: 14px; margin-bottom: 14px; }}
      code {{ font-size: 12px; }}
      a {{ color: #0f6a8b; }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <p><a href="/">Back to Analyzer</a></p>
      <div class="card">
        <h3>Could not analyze local replay</h3>
        <p>File: <code>{html.escape(str(p))}</code></p>
        <p>Error: <code>{detail}</code></p>
        <p>This usually means the downloaded file is incomplete or not a full replay file.</p>
        <p>Re-import this match and try again.</p>
      </div>
    </div>
  </body>
</html>
"""


def _icon_url(category: str, name: str | None) -> str | None:
    if not name:
        return None
    safe = "".join(c if c.isalnum() or c in "_.-" else "_" for c in name)
    if category == "template":
        rel = f"{safe}.png"
    else:
        rel = f"{category}s/{safe}.png"
    if not (_ICONS_DIR / rel).exists():
        return None
    return f"/icons/{rel}"


def _enrich_timeline_with_icons(report: dict[str, Any]) -> dict[str, Any]:
    for player in report.get("players", []):
        for item in player.get("timeline", []):
            icon = (
                (_icon_url("template", item.get("template_name")) if item.get("template_name") else None)
                or (_icon_url("science", item.get("science_name")) if item.get("science_name") else None)
                or (_icon_url("upgrade", item.get("upgrade_name")) if item.get("upgrade_name") else None)
                or (_icon_url("power", item.get("power_name")) if item.get("power_name") else None)
                or (_icon_url("action", item.get("action")) if item.get("action") else None)
            )
            item["icon_url"] = icon
    return report


_DEMO_REPLAY = Path(__file__).parent / "demo.rep"


@app.get("/api/demo")
async def api_demo() -> JSONResponse:
    if not _DEMO_REPLAY.exists():
        raise HTTPException(status_code=404, detail="Demo replay not bundled.")
    try:
        report = analyze_replay_bytes(_DEMO_REPLAY.read_bytes())
    except ReplayParseError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    report["filename"] = _DEMO_REPLAY.name
    return JSONResponse(_enrich_timeline_with_icons(report))


@app.post("/api/analyze")
async def api_analyze(file: UploadFile = File(...)) -> JSONResponse:
    if not file.filename.lower().endswith(".rep"):
        raise HTTPException(status_code=400, detail="Please upload a .rep replay file.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    try:
        report = analyze_replay_bytes(data)
    except ReplayParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    report["filename"] = file.filename
    return JSONResponse(_enrich_timeline_with_icons(report))


@app.get("/report", response_class=HTMLResponse)
async def report_shell() -> str:
    index = _FRONTEND_DIST / "index.html"
    if index.exists():
        return index.read_text(encoding="utf-8")
    return """<!doctype html><html><body>
<h1>React frontend not built</h1>
<p>Run <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code> to produce
<code>replay_tool/static/index.html</code>.</p>
<p><a href="/">Back</a></p>
</body></html>"""


@app.post("/analyze", response_class=HTMLResponse)
async def analyze(file: UploadFile = File(...)) -> str:
    if not file.filename.lower().endswith(".rep"):
        raise HTTPException(status_code=400, detail="Please upload a .rep replay file.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        report = analyze_replay_bytes(data)
    except ReplayParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    escaped_json = html.escape(json.dumps(report, indent=2))
    replay = report["replay"]
    top_meaningful = report.get("top_meaningful_orders_overall", [])
    id_resolution = report.get("id_resolution", {})
    players = report.get("players", [])

    top_meaningful_rows = "".join(
        f"<tr><td>{html.escape(item['order'])}</td><td>{item['count']}</td></tr>"
        for item in top_meaningful[:12]
    )

    player_rows = []
    player_timelines = []
    player_maps = []

    for p in players:
        top_actions = ", ".join(
            f"{i['order']} ({i['count']})" for i in p.get("top_meaningful_orders", [])[:5]
        )
        player_rows.append(
            "<tr>"
            f"<td>{p['player_number']}</td>"
            f"<td>{html.escape(p['player_name'])}</td>"
            f"<td>{p['meaningful_actions']}</td>"
            f"<td>{p['effective_apm']}</td>"
            f"<td>{p['macro_actions']}</td>"
            f"<td>{p['micro_actions']}</td>"
            f"<td>{p['economy_actions']}</td>"
            f"<td>{html.escape(top_actions)}</td>"
            "</tr>"
        )
        timeline_items = []
        for item in p.get("timeline", []):
            icon_uri = (
                get_template_icon_data_uri(item.get("template_name"))
                or get_science_icon_data_uri(item.get("science_name"))
                or get_upgrade_icon_data_uri(item.get("upgrade_name"))
                or get_power_icon_data_uri(item.get("power_name"))
                or get_action_icon_data_uri(item.get("action"))
            )
            sec = int(item.get("timecode", 0) / 30)
            timeline_items.append(
                f"<div data-sec=\"{sec}\" class=\"timeline-item{' timeline-move' if item.get('action') == 'MoveTo' else ''}{'' if icon_uri else ' timeline-noicon'}\">"
                + (f"<img class=\"tl-icon\" src=\"{html.escape(icon_uri)}\" alt=\"icon\" />" if icon_uri else "")
                + f"<span class=\"tl-main\"><code>{html.escape(str(item['clock']))}</code> - "
                + f"{html.escape(str(item['label']))}"
                + (f" <strong>{html.escape(str(item.get('template_name_human') or item.get('template_name')))}</strong>" if item.get("template_name") else "")
                + (f" <strong>{html.escape(str(item.get('upgrade_name_human') or item.get('upgrade_name')))}</strong>" if item.get("upgrade_name") else "")
                + (f" <strong>{html.escape(str(item.get('science_name_human') or item.get('science_name')))}</strong>" if item.get("science_name") else "")
                + (f" <strong>{html.escape(str(item.get('power_name_human') or item.get('power_name')))}</strong>" if item.get("power_name") else "")
                + "</span>"
                + (f"<code class=\"tl-detail\">{html.escape(str(item['detail']))}</code>" if item.get("detail") else "")
                + "</div>"
            )
        player_timelines.append(
            "<details open>"
            f"<summary><strong>{html.escape(p['player_name'])}</strong> "
            f"(Player {p['player_number']}, {p['meaningful_actions']} meaningful actions)</summary>"
            f"<div class=\"timeline-wrap\">"
            f"<div class=\"timeline-source\">{''.join(timeline_items)}</div>"
            f"<div class=\"timeline-buckets\"></div>"
            "</div>"
            "</details>"
        )
        map_events_json = html.escape(json.dumps(p.get("map_events", [])))
        player_maps.append(
            "<details>"
            f"<summary><strong>{html.escape(p['player_name'])}</strong> "
            f"(Player {p['player_number']})</summary>"
            "<div class=\"map-wrap\">"
            f"<canvas class=\"player-map\" data-events=\"{map_events_json}\" width=\"860\" height=\"360\"></canvas>"
            "<div class=\"map-meta\"></div>"
            "<div class=\"map-legend\">"
            "<span><i class=\"dot dot-move\"></i>Move path</span>"
            "<span><i class=\"dot dot-build\"></i>Build</span>"
            "<span><i class=\"dot dot-start\"></i>Start</span>"
            "<span><i class=\"dot dot-end\"></i>End</span>"
            "</div>"
            "</div>"
            "</details>"
        )
    player_rows_html = "".join(player_rows)
    player_timelines_html = "".join(player_timelines)
    player_maps_html = "".join(player_maps)
    unresolved = id_resolution.get("unresolved_template_ids", [])
    unresolved_rows = "".join(
        f"<tr><td>{row['template_id']}</td><td>{row['count']}</td></tr>"
        for row in unresolved[:20]
    )
    lookup_file = html.escape(str(id_resolution.get("lookup_file", "replay_tool/id_lookup.json")))

    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Replay Report</title>
    <style>
      body {{ font-family: "Segoe UI", Tahoma, sans-serif; background: #f6f3ec; margin: 0; }}
      .wrap {{ width: calc(100vw - 24px); max-width: none; margin: 12px auto; padding: 0 12px; box-sizing: border-box; }}
      a {{ color: #0f6a8b; }}
      .card {{ background: #fffdf7; border: 1px solid #ded8cb; border-radius: 12px; padding: 14px; margin-bottom: 14px; }}
      table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
      th, td {{ border-bottom: 1px solid #e8e1d2; padding: 8px; text-align: left; vertical-align: top; }}
      th {{ background: #f2ecdf; }}
      details {{ margin: 10px 0; }}
      .timeline-wrap {{ max-height: 420px; overflow-y: auto; border: 1px solid #e8e1d2; border-radius: 8px; padding: 10px; background: #fff; }}
      .main-timeline {{ min-height: calc(100vh - 20px); display: flex; flex-direction: column; }}
      .timeline-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: start; }}
      .timeline-grid > details {{ margin: 0; }}
      .main-timeline .timeline-wrap {{ max-height: none; height: calc(100vh - 140px); }}
      @media (max-width: 1200px) {{
        .timeline-grid {{ grid-template-columns: 1fr; }}
      }}
      .collapsed summary {{ cursor: pointer; font-weight: 700; }}
      .collapsed[open] summary {{ margin-bottom: 10px; }}
      .timeline-source {{ display: none; }}
      .timeline-bucket {{ margin-bottom: 10px; }}
      .bucket-label {{ font-size: 12px; color: #5b6777; margin-top: 6px; font-weight: 600; }}
      .bucket-actions {{ display: flex; flex-wrap: wrap; gap: 8px; }}
      .timeline-item {{ display: inline-flex; align-items: center; gap: 6px; border: 1px solid #dcd4c6; border-radius: 8px; padding: 5px 7px; background: #f9f7f2; }}
      .tl-main {{ white-space: nowrap; }}
      .tl-detail {{ margin-left: 2px; }}
      .tl-icon {{ width: 40px; height: 40px; vertical-align: -12px; margin-right: 8px; border-radius: 3px; border: 1px solid #d7ceb9; background: #111; }}
      .timeline-filters {{ margin: 8px 0 12px 0; }}
      .timeline-filters label {{ display: inline-flex; gap: 8px; align-items: center; }}
      .hide-text .tl-main, .hide-text .tl-detail {{ display: none; }}
      .map-wrap {{ border: 1px solid #e8e1d2; border-radius: 8px; background: #fff; padding: 10px; margin-top: 8px; }}
      .player-map {{ width: 100%; height: auto; border: 1px solid #d8d0c2; border-radius: 8px; background: linear-gradient(180deg, #f6f2e8 0%, #eee7d8 100%); }}
      .map-meta {{ font-size: 12px; color: #5f6d7c; margin-top: 7px; }}
      .map-legend {{ display: flex; gap: 18px; margin-top: 8px; font-size: 13px; color: #4b5868; }}
      .map-legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
      .dot {{ width: 10px; height: 10px; border-radius: 999px; display: inline-block; }}
      .dot-move {{ background: #1f6fb2; }}
      .dot-build {{ background: #c4572d; }}
      .dot-start {{ background: #2e8b57; }}
      .dot-end {{ background: #b42828; }}
      pre {{ white-space: pre-wrap; background: #10151b; color: #d3dde8; padding: 14px; border-radius: 10px; }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <p><a href="/">Upload another replay</a></p>
      <div class="card">
        <strong>Game Date &amp; Time</strong>
        <p>
          Start: <code>{html.escape(str(replay.get('start_time_utc') or 'Unknown'))}</code><br/>
          End: <code>{html.escape(str(replay.get('end_time_utc') or 'Unknown'))}</code>
        </p>
      </div>
      <div class="card main-timeline">
        <div class="timeline-grid">{player_timelines_html}</div>
        <h2>Analysis: {html.escape(file.filename)}</h2>
        <strong>Action Timeline (Main View)</strong>
        <p>Open a player and follow actions in the exact replay sequence.</p>
        <div class="timeline-filters">
          <label>
            <input id="hide-move-actions" type="checkbox" />
            Hide Move actions
          </label>
          <label style="margin-left: 14px;">
            <input id="hide-action-text" type="checkbox" checked />
            Hide action text (icons only)
          </label>
          <label style="margin-left: 14px;">
            Group seconds:
            <input id="group-seconds" type="number" min="1" max="60" step="1" value="60" style="width:60px;" />
          </label>
        </div>
      </div>
      <details class="card collapsed">
        <summary>Replay Summary</summary>
        <p>
          Map: <code>{html.escape(str(replay.get('map_file')))}</code><br/>
          Duration: <code>{replay.get('duration_seconds_estimate')}s</code><br/>
          Total commands: <code>{replay.get('total_actions')}</code><br/>
          Meaningful commands: <code>{replay.get('meaningful_actions_total')}</code>
        </p>
      </details>
      <details class="card collapsed">
        <summary>Players (Meaningful View)</summary>
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
          <tbody>{player_rows_html}</tbody>
        </table>
      </details>
      <details class="card collapsed">
        <summary>Top Meaningful Actions (All Players)</summary>
        <table>
          <thead><tr><th>Action</th><th>Count</th></tr></thead>
          <tbody>{top_meaningful_rows}</tbody>
        </table>
      </details>
      <details class="card collapsed">
        <summary>Movement &amp; Build Map</summary>
        <p>Player command positions from replay input. Blue: movement, orange: build.</p>
        <div class="timeline-filters">
          <label>
            From sec:
            <input id="map-sec-from" type="number" min="0" step="1" placeholder="0" style="width:80px;" />
          </label>
          <label style="margin-left: 14px;">
            To sec:
            <input id="map-sec-to" type="number" min="0" step="1" placeholder="all" style="width:80px;" />
          </label>
        </div>
        {player_maps_html}
      </details>
      <details class="card collapsed">
        <summary>Template Name Resolution</summary>
        <p>Edit <code>{lookup_file}</code> to map IDs to real names.</p>
        <table>
          <thead><tr><th>Unresolved template_id</th><th>Count</th></tr></thead>
          <tbody>{unresolved_rows}</tbody>
        </table>
      </details>
      <details class="card collapsed">
        <summary>Raw JSON</summary>
        <pre>{escaped_json}</pre>
      </details>
    </div>
    <script>
      (function() {{
        const checkbox = document.getElementById("hide-move-actions");
        const hideTextCheckbox = document.getElementById("hide-action-text");
        const groupSecondsInput = document.getElementById("group-seconds");
        if (!checkbox) return;
        const toClock = (s) => {{
          const m = Math.floor(s / 60);
          const ss = s % 60;
          return String(m).padStart(2, "0") + ":" + String(ss).padStart(2, "0");
        }};
        const apply = () => {{
          const groupSeconds = Math.max(1, Math.min(60, parseInt(groupSecondsInput?.value || "60", 10) || 60));
          document.querySelectorAll(".timeline-move").forEach((el) => {{
            el.style.display = checkbox.checked ? "none" : "";
          }});
          const wraps = Array.from(document.querySelectorAll(".timeline-wrap"));
          const perWrap = wraps.map((el) => {{
            if (hideTextCheckbox && hideTextCheckbox.checked) {{
              el.classList.add("hide-text");
            }} else {{
              el.classList.remove("hide-text");
            }}
            const sourceItems = Array.from(el.querySelectorAll(".timeline-source .timeline-item"));
            const visibleByBucket = new Map();
            sourceItems.forEach((item) => {{
              const hiddenByMove = item.classList.contains("timeline-move") && checkbox.checked;
              const hiddenByNoIcon = item.classList.contains("timeline-noicon") && hideTextCheckbox && hideTextCheckbox.checked;
              const visible = !(hiddenByMove || hiddenByNoIcon);
              item.style.display = visible ? "" : "none";
              if (!visible) return;
              const sec = parseInt(item.getAttribute("data-sec") || "0", 10) || 0;
              const start = Math.floor(sec / groupSeconds) * groupSeconds;
              if (!visibleByBucket.has(start)) visibleByBucket.set(start, []);
              visibleByBucket.get(start).push(item);
            }});
            return {{ el, visibleByBucket }};
          }});

          const allStarts = new Set();
          const maxItemsPerBucket = new Map();
          perWrap.forEach(({{ visibleByBucket }}) => {{
            visibleByBucket.forEach((items, start) => {{
              allStarts.add(start);
              const prev = maxItemsPerBucket.get(start) || 0;
              if (items.length > prev) maxItemsPerBucket.set(start, items.length);
            }});
          }});
          const sortedStarts = Array.from(allStarts).sort((a, b) => a - b);

          // Pass 1: render every wrap with every bucket (empty buckets included
          // for symmetry). Tag each bucket with its start so we can align later.
          perWrap.forEach(({{ el, visibleByBucket }}) => {{
            const bucketsHost = el.querySelector(".timeline-buckets");
            if (!bucketsHost) return;
            bucketsHost.innerHTML = "";
            sortedStarts.forEach((start) => {{
              const items = visibleByBucket.get(start) || [];
              const bucketEl = document.createElement("div");
              bucketEl.className = "timeline-bucket";
              bucketEl.dataset.start = String(start);
              const actionsEl = document.createElement("div");
              actionsEl.className = "bucket-actions";
              items.forEach((item) => {{
                const clone = item.cloneNode(true);
                clone.style.display = "";
                actionsEl.appendChild(clone);
              }});
              bucketEl.appendChild(actionsEl);
              const labelEl = document.createElement("div");
              labelEl.className = "bucket-label";
              labelEl.textContent = `${{toClock(start)}}-${{toClock(start + groupSeconds - 1)}}`;
              bucketEl.appendChild(labelEl);
              bucketsHost.appendChild(bucketEl);
            }});
          }});

          // Pass 2: measure each bucket's natural height across all wraps,
          // then set min-height to the max so rows line up.
          requestAnimationFrame(() => {{
            const heightByStart = new Map();
            perWrap.forEach(({{ el }}) => {{
              el.querySelectorAll(".timeline-bucket").forEach((b) => {{
                b.style.minHeight = "";
                const start = parseInt(b.dataset.start || "0", 10);
                const h = b.getBoundingClientRect().height;
                const prev = heightByStart.get(start) || 0;
                if (h > prev) heightByStart.set(start, h);
              }});
            }});
            perWrap.forEach(({{ el }}) => {{
              el.querySelectorAll(".timeline-bucket").forEach((b) => {{
                const start = parseInt(b.dataset.start || "0", 10);
                const h = heightByStart.get(start) || 0;
                if (h > 0) b.style.minHeight = h + "px";
              }});
            }});
          }});
        }};
        checkbox.addEventListener("change", apply);
        if (hideTextCheckbox) {{
          hideTextCheckbox.addEventListener("change", apply);
        }}
        if (groupSecondsInput) {{
          groupSecondsInput.addEventListener("input", apply);
        }}
        apply();

        const timelineWraps = Array.from(document.querySelectorAll(".main-timeline .timeline-wrap"));
        let syncingScroll = false;
        timelineWraps.forEach((wrap) => {{
          wrap.addEventListener("scroll", () => {{
            if (syncingScroll) return;
            syncingScroll = true;
            const source = wrap;
            const sourceMax = Math.max(1, source.scrollHeight - source.clientHeight);
            const ratio = source.scrollTop / sourceMax;
            timelineWraps.forEach((other) => {{
              if (other === source) return;
              const otherMax = Math.max(0, other.scrollHeight - other.clientHeight);
              other.scrollTop = ratio * otherMax;
            }});
            syncingScroll = false;
          }}, {{ passive: true }});
        }});

        const drawMaps = () => {{
          const fromInput = document.getElementById("map-sec-from");
          const toInput = document.getElementById("map-sec-to");
          const fromSecRaw = parseInt(fromInput?.value || "", 10);
          const toSecRaw = parseInt(toInput?.value || "", 10);
          let fromSec = Number.isFinite(fromSecRaw) ? Math.max(0, fromSecRaw) : 0;
          let toSec = Number.isFinite(toSecRaw) ? Math.max(0, toSecRaw) : Number.POSITIVE_INFINITY;
          if (toSec < fromSec) {{
            const tmp = fromSec;
            fromSec = toSec;
            toSec = tmp;
          }}
          const canvases = document.querySelectorAll(".player-map");
          canvases.forEach((canvas) => {{
            const raw = canvas.getAttribute("data-events");
            if (!raw) return;
            const meta = canvas.parentElement?.querySelector(".map-meta");
            let events = [];
            try {{
              events = JSON.parse(raw);
            }} catch (_err) {{
              return;
            }}
            if (!Array.isArray(events) || events.length === 0) {{
              const ctx0 = canvas.getContext("2d");
              if (!ctx0) return;
              ctx0.clearRect(0, 0, canvas.width, canvas.height);
              ctx0.fillStyle = "#6f7d8d";
              ctx0.font = "14px Segoe UI";
              ctx0.fillText("No position events found.", 12, 24);
              if (meta) meta.textContent = "No movement/build coordinate events in this replay.";
              return;
            }}
            const points = events
              .filter((e) => Number.isFinite(e?.x) && Number.isFinite(e?.y))
              .filter((e) => {{
                const sec = Number.isFinite(e?.timecode) ? (e.timecode / 30) : -1;
                return sec >= fromSec && sec <= toSec;
              }});
            if (points.length === 0) {{
              const ctx1 = canvas.getContext("2d");
              if (!ctx1) return;
              ctx1.clearRect(0, 0, canvas.width, canvas.height);
              ctx1.fillStyle = "#6f7d8d";
              ctx1.font = "14px Segoe UI";
              ctx1.fillText("No position events in selected range.", 12, 24);
              if (meta) meta.textContent = `No events in selected range (${{fromSec}}s-${{Number.isFinite(toSec) ? toSec : "all"}}s).`;
              return;
            }}
            const minX = Math.min(...points.map((p) => p.x));
            const maxX = Math.max(...points.map((p) => p.x));
            const minY = Math.min(...points.map((p) => p.y));
            const maxY = Math.max(...points.map((p) => p.y));
            const pad = 18;
            const w = canvas.width;
            const h = canvas.height;
            const rangeX = Math.max(1, maxX - minX);
            const rangeY = Math.max(1, maxY - minY);
            const sx = (w - pad * 2) / rangeX;
            const sy = (h - pad * 2) / rangeY;
            const scale = Math.min(sx, sy);
            const usedW = rangeX * scale;
            const usedH = rangeY * scale;
            const xOff = (w - usedW) / 2;
            const yOff = (h - usedH) / 2;
            const tx = (x) => xOff + (x - minX) * scale;
            const ty = (y) => h - (yOff + (y - minY) * scale);

            const ctx = canvas.getContext("2d");
            if (!ctx) return;
            ctx.clearRect(0, 0, w, h);
            const bg = ctx.createLinearGradient(0, 0, 0, h);
            bg.addColorStop(0, "#f5f0e4");
            bg.addColorStop(1, "#ebe3d3");
            ctx.fillStyle = bg;
            ctx.fillRect(0, 0, w, h);
            ctx.strokeStyle = "rgba(120, 111, 90, 0.2)";
            ctx.lineWidth = 1.1;
            for (let i = 1; i < 4; i++) {{
              const gx = (w / 4) * i;
              const gy = (h / 4) * i;
              ctx.beginPath();
              ctx.moveTo(gx, 0);
              ctx.lineTo(gx, h);
              ctx.stroke();
              ctx.beginPath();
              ctx.moveTo(0, gy);
              ctx.lineTo(w, gy);
              ctx.stroke();
            }}

            const movePoints = points.filter((p) => p.kind !== "build");
            const buildPoints = points.filter((p) => p.kind === "build");
            const firstPoint = points[0];
            const lastPoint = points[points.length - 1];

            if (movePoints.length > 0) {{
              ctx.strokeStyle = "rgba(31,111,178,0.62)";
              ctx.lineWidth = 2.2;
              ctx.beginPath();
              movePoints.forEach((p, idx) => {{
                const x = tx(p.x);
                const y = ty(p.y);
                if (idx === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
              }});
              ctx.stroke();
            }}

            movePoints.forEach((p) => {{
              ctx.fillStyle = "#1f6fb2";
              ctx.beginPath();
              ctx.arc(tx(p.x), ty(p.y), 2.8, 0, Math.PI * 2);
              ctx.fill();
            }});

            buildPoints.forEach((p) => {{
              const x = tx(p.x);
              const y = ty(p.y);
              ctx.strokeStyle = "#c4572d";
              ctx.lineWidth = 2.0;
              ctx.beginPath();
              ctx.rect(x - 4, y - 4, 8, 8);
              ctx.stroke();
            }});

            if (firstPoint) {{
              const x = tx(firstPoint.x);
              const y = ty(firstPoint.y);
              ctx.fillStyle = "#2e8b57";
              ctx.beginPath();
              ctx.arc(x, y, 4.5, 0, Math.PI * 2);
              ctx.fill();
            }}
            if (lastPoint) {{
              const x = tx(lastPoint.x);
              const y = ty(lastPoint.y);
              ctx.fillStyle = "#b42828";
              ctx.beginPath();
              ctx.arc(x, y, 4.5, 0, Math.PI * 2);
              ctx.fill();
            }}

            ctx.fillStyle = "#5c6978";
            ctx.font = "12px Segoe UI";
            const toTxt = Number.isFinite(toSec) ? String(toSec) : "all";
            ctx.fillText(`Range: ${{fromSec}}s - ${{toTxt}}s`, 10, 16);
            if (meta) {{
              meta.textContent = `Events: ${{points.length}} (Moves: ${{movePoints.length}}, Builds: ${{buildPoints.length}}) | X: ${{minX.toFixed(0)}}-${{maxX.toFixed(0)}} | Y: ${{minY.toFixed(0)}}-${{maxY.toFixed(0)}}`;
            }}
          }});
        }};
        const mapFrom = document.getElementById("map-sec-from");
        const mapTo = document.getElementById("map-sec-to");
        if (mapFrom) {{
          mapFrom.addEventListener("input", drawMaps);
        }}
        if (mapTo) {{
          mapTo.addEventListener("input", drawMaps);
        }}
        document.querySelectorAll("details").forEach((d) => {{
          d.addEventListener("toggle", () => {{
            apply();
            drawMaps();
          }});
        }});
        drawMaps();
      }})();
    </script>
  </body>
</html>
"""
