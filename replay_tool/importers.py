from __future__ import annotations

from dataclasses import dataclass
import html
import json
import logging
from pathlib import Path
import re
import urllib.request
from urllib.parse import urljoin
import urllib.error
import time

from replay_tool.analyzer import ReplayParseError, parse_replay_bytes, parse_replay_preview_bytes


BASE_URL = "https://www.playgenerals.online"
GOMATCH_URL = "https://gomatch.community-outpost.com"
logger = logging.getLogger(__name__)


@dataclass
class Participant:
    name: str
    side: str


@dataclass
class MatchPage:
    match_id: int
    map_name: str
    participants: list[Participant]
    replay_links: list[tuple[str, str | None]]


def _http_get_text(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ReplayTool/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _http_get_bytes(url: str, timeout: int = 40) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ReplayTool/1.0",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _http_get_bytes_retry(url: str, timeout: int = 40, attempts: int = 3) -> bytes:
    last_exc: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            return _http_get_bytes(url=url, timeout=timeout)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            # 404 is usually permanent; do not spend all retries on it.
            if exc.code == 404:
                break
        except Exception as exc:
            last_exc = exc
        if i + 1 < attempts:
            time.sleep(0.35 * (i + 1))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("download failed")


def _http_post_json(url: str, payload: dict[str, object], headers: dict[str, str], timeout: int = 30) -> dict[str, object]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ReplayTool/1.0",
            **headers,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    data = json.loads(raw)
    if isinstance(data, dict):
        return data
    return {}


def _clean_html_text(value: str) -> str:
    txt = re.sub(r"<[^>]+>", "", value)
    txt = txt.replace("&nbsp;", " ").replace("&amp;", "&")
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def _slug(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return s[:80] or "unknown"


def _normalize_replay_url(url: str) -> str:
    u = html.unescape((url or "").strip())
    # Common trailing junk when extracted from HTML blobs.
    u = u.rstrip("',\">)")
    return u


def _replay_validation(data: bytes) -> tuple[bool, str, str]:
    if not data:
        return False, "none", "empty file"
    try:
        parse_replay_bytes(data)
        return True, "full", ""
    except Exception as full_exc:
        try:
            parse_replay_preview_bytes(data)
            return True, "preview", ""
        except Exception as preview_exc:
            full_reason = str(full_exc).strip() or full_exc.__class__.__name__
            preview_reason = str(preview_exc).strip() or preview_exc.__class__.__name__
            return False, "none", f"full={full_reason}; preview={preview_reason}"


def fetch_recent_match_ids(limit: int = 50) -> list[int]:
    html = _http_get_text(f"{BASE_URL}/matchhistory")
    ids = [int(m) for m in re.findall(r"/viewmatch/(\d+)", html)]
    seen: set[int] = set()
    out: list[int] = []
    for mid in ids:
        if mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
        if len(out) >= limit:
            break
    return out


def _get_gomatch_search_credentials() -> tuple[str, str]:
    page = _http_get_text(f"{GOMATCH_URL}/")
    script_paths = re.findall(r"<script[^>]+src=\"([^\"]+)\"", page, re.IGNORECASE)
    bundle_url = None
    for src in script_paths:
        if "/assets/index-" in src and src.endswith(".js"):
            bundle_url = urljoin(GOMATCH_URL, src)
            break
    if not bundle_url:
        raise RuntimeError("Could not discover gomatch frontend bundle.")
    bundle = _http_get_text(bundle_url, timeout=40)
    use_m = re.search(r"new\s+\w+\(\{host:(\w+),apiKey:(\w+)\}\)", bundle)
    if not use_m:
        raise RuntimeError("Could not extract gomatch search host/api key.")
    host_var, key_var = use_m.group(1), use_m.group(2)
    host_m = re.search(
        rf"{re.escape(host_var)}\s*=\s*\"([^\"]*gomatch-search\.community-outpost\.com[^\"]*)\"",
        bundle,
        re.IGNORECASE,
    )
    key_m = re.search(
        rf"{re.escape(key_var)}\s*=\s*\"([a-f0-9]{{40,80}})\"",
        bundle,
        re.IGNORECASE,
    )
    if not host_m or not key_m:
        raise RuntimeError("Could not extract gomatch search host/api key values.")
    host = host_m.group(1).rstrip("/")
    api_key = key_m.group(1)
    return host, api_key


def search_gomatch_matches(player_filter: str, map_filter: str, army_filter: str, limit: int) -> list[dict[str, object]]:
    host, api_key = _get_gomatch_search_credentials()
    q = player_filter.strip() or map_filter.strip() or army_filter.strip() or ""
    out: list[dict[str, object]] = []
    seen: set[int] = set()

    headers = {"Authorization": f"Bearer {api_key}"}
    page = 1
    per_page = min(max(limit, 20), 100)
    max_pages = 15
    player_q = player_filter.strip().lower()
    map_q = map_filter.strip().lower()
    army_q = army_filter.strip().lower()

    while page <= max_pages and len(out) < limit:
        payload = {
            "q": q,
            "page": page,
            "hitsPerPage": per_page,
            "sort": ["time_started_ts:desc"],
        }
        data = _http_post_json(f"{host}/indexes/matches/search", payload, headers=headers, timeout=35)
        hits = data.get("hits", [])
        if not isinstance(hits, list) or not hits:
            break

        for hit in hits:
            if not isinstance(hit, dict):
                continue
            mid_raw = hit.get("match_id")
            try:
                mid = int(mid_raw)
            except Exception:
                continue
            if mid in seen:
                continue

            members = hit.get("members", [])
            if not isinstance(members, list):
                members = []
            players = []
            for m in members:
                if not isinstance(m, dict):
                    continue
                players.append(
                    {
                        "display_name": str(m.get("display_name") or ""),
                        "side_name": str(m.get("side_name") or ""),
                    }
                )

            if player_q and not any(player_q in p["display_name"].lower() for p in players):
                continue
            if map_q and map_q not in str(hit.get("map_name") or "").lower():
                continue
            if army_q and not any(army_q in p["side_name"].lower() for p in players):
                continue

            seen.add(mid)
            out.append(hit)
            if len(out) >= limit:
                break

        total_pages = data.get("totalPages")
        if isinstance(total_pages, int) and page >= total_pages:
            break
        page += 1

    return out


def fetch_match_page(match_id: int) -> MatchPage:
    html = _http_get_text(f"{BASE_URL}/viewmatch/{match_id}")

    map_name = "Unknown"
    map_match = re.search(r"Map Name</td><th>(.*?)</th>", html, re.IGNORECASE | re.DOTALL)
    if map_match:
        map_name = _clean_html_text(map_match.group(1))

    participants: list[Participant] = []
    participant_rows = re.findall(r"<tr>\s*<th><span class=\"lbl\">Name</span>(.*?)</th>(.*?)</tr>", html, re.IGNORECASE | re.DOTALL)
    seen_participants: set[tuple[str, str]] = set()
    for name_raw, rest in participant_rows:
        name = _clean_html_text(name_raw)
        side_match = re.search(r"/images/teams/([a-z0-9_]+)\.(?:webp|png|jpg)", rest, re.IGNORECASE)
        side = side_match.group(1) if side_match else "unknown"
        key = (name.lower(), side.lower())
        if name and key not in seen_participants:
            seen_participants.add(key)
            participants.append(Participant(name=name, side=side))

    replay_links: list[tuple[str, str | None]] = []
    seen_links: set[str] = set()
    anti_start = html.lower().find("anticheat data")
    anti_block = html[anti_start:] if anti_start >= 0 else html
    anti_rows = re.findall(r"<tr>\s*<th><span class=\"lbl\">Name</span>(.*?)</th>\s*<td>(.*?)</td>\s*</tr>", anti_block, re.IGNORECASE | re.DOTALL)
    for name_raw, row_html in anti_rows:
        owner = _clean_html_text(name_raw)
        for link in re.findall(r"href=\"(https?://[^\"]+?\.rep)\"", row_html, re.IGNORECASE):
            link = _normalize_replay_url(link)
            if link in seen_links:
                continue
            seen_links.add(link)
            replay_links.append((link, owner or None))

    # Always scan full page as fallback because some matches expose replay links
    # outside the anticheat rows (or missing owner labels).
    for link in re.findall(r"(https?://[^\s\"']+?\.rep)", html, re.IGNORECASE):
        link = _normalize_replay_url(link)
        if link in seen_links:
            continue
        seen_links.add(link)
        replay_links.append((link, None))

    return MatchPage(
        match_id=match_id,
        map_name=map_name,
        participants=participants,
        replay_links=replay_links,
    )


def import_generals_online_replays(
    output_dir: str,
    player_filter: str = "",
    map_filter: str = "",
    army_filter: str = "",
    max_matches: int = 30,
    debug: bool = False,
) -> dict[str, object]:
    out_dir = Path(output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    player_q = player_filter.strip().lower()
    map_q = map_filter.strip().lower()
    army_q = army_filter.strip().lower()

    # Prefer the indexed search backend (supports historic queries like "LeadeR"),
    # then fallback to recent match history scraping if needed.
    indexed_hits: list[dict[str, object]] = []
    try:
        indexed_hits = search_gomatch_matches(
            player_filter=player_filter,
            map_filter=map_filter,
            army_filter=army_filter,
            limit=max_matches,
        )
    except Exception:
        indexed_hits = []

    match_ids = []
    indexed_by_id: dict[int, dict[str, object]] = {}
    if indexed_hits:
        for h in indexed_hits:
            try:
                mid = int(h.get("match_id"))
            except Exception:
                continue
            match_ids.append(mid)
            indexed_by_id[mid] = h
    else:
        match_ids = fetch_recent_match_ids(limit=max_matches * 3)
    imported_rows: list[dict[str, object]] = []
    scanned = 0
    matched = 0
    downloaded = 0
    skipped_existing = 0
    failed = 0
    debug_events: list[dict[str, object]] = []

    for mid in match_ids:
        if matched >= max_matches:
            break
        scanned += 1
        try:
            match = fetch_match_page(mid)
            if debug:
                debug_events.append(
                    {
                        "match_id": mid,
                        "event": "match_page_ok",
                        "participants": len(match.participants),
                        "replay_links": len(match.replay_links),
                    }
                )
        except Exception as exc:
            failed += 1
            if debug:
                debug_events.append(
                    {
                        "match_id": mid,
                        "event": "match_page_error",
                        "error": str(exc),
                    }
                )
            imported_rows.append(
                {
                    "match_id": mid,
                    "status": "error",
                    "error": f"Failed to fetch match page: {exc}",
                }
            )
            continue

        participants = match.participants
        hit = indexed_by_id.get(mid)
        if hit and isinstance(hit, dict):
            members = hit.get("members", [])
            if isinstance(members, list) and members:
                rebuilt: list[Participant] = []
                seen_mem: set[tuple[str, str]] = set()
                for mem in members:
                    if not isinstance(mem, dict):
                        continue
                    name = str(mem.get("display_name") or "").strip()
                    side = str(mem.get("side_name") or "unknown").strip()
                    if not name:
                        continue
                    key = (name.lower(), side.lower())
                    if key in seen_mem:
                        continue
                    seen_mem.add(key)
                    rebuilt.append(Participant(name=name, side=side))
                if rebuilt:
                    participants = rebuilt
        if player_q and not any(player_q in p.name.lower() for p in participants):
            continue
        if map_q and map_q not in match.map_name.lower():
            continue
        if army_q and not any(army_q in p.side.lower() for p in participants):
            continue

        matched += 1
        selected_links: list[tuple[str, str | None]] = []
        if player_q:
            for link, owner in match.replay_links:
                if owner and player_q in owner.lower():
                    selected_links.append((link, owner))
        for link_owner in match.replay_links:
            if link_owner not in selected_links:
                selected_links.append(link_owner)

        if not selected_links:
            failed += 1
            if debug:
                debug_events.append(
                    {
                        "match_id": mid,
                        "event": "no_replay_link",
                    }
                )
            imported_rows.append(
                {
                    "match_id": mid,
                    "status": "error",
                    "map_name": match.map_name,
                    "players": ", ".join(f"{p.name} ({p.side})" for p in participants),
                    "error": "No replay link found",
                }
            )
            continue

        owner_slug = _slug(selected_links[0][1] or "unknown")
        map_slug = _slug(match.map_name)
        file_name = f"match_{mid}_{owner_slug}_{map_slug}.rep"
        out_path = out_dir / file_name

        if out_path.exists():
            try:
                existing_data = out_path.read_bytes()
            except Exception:
                existing_data = b""
            existing_ok, existing_mode, _ = _replay_validation(existing_data)
            if existing_ok:
                skipped_existing += 1
                if debug:
                    debug_events.append(
                        {
                            "match_id": mid,
                            "event": "exists_valid",
                            "mode": existing_mode,
                            "path": str(out_path),
                        }
                    )
                imported_rows.append(
                    {
                        "match_id": mid,
                        "status": "exists",
                        "validation_mode": existing_mode,
                        "map_name": match.map_name,
                        "players": ", ".join(f"{p.name} ({p.side})" for p in participants),
                        "saved_path": str(out_path),
                        "replay_url": selected_links[0][0],
                    }
                )
                continue
            try:
                out_path.unlink(missing_ok=True)
            except Exception:
                pass

        try:
            replay_bytes: bytes | None = None
            chosen_url: str | None = None
            chosen_owner: str | None = None
            chosen_validation_mode = "none"
            last_error: str | None = None
            attempt_debug: list[dict[str, str]] = []
            for candidate_url, candidate_owner in selected_links:
                try:
                    candidate_bytes = _http_get_bytes_retry(urljoin(BASE_URL, candidate_url))
                except Exception as exc:
                    last_error = f"Download failed: {exc}"
                    attempt_debug.append(
                        {
                            "url": candidate_url,
                            "owner": str(candidate_owner or ""),
                            "result": "download_error",
                            "error": str(exc),
                        }
                    )
                    continue
                valid, mode, reason = _replay_validation(candidate_bytes)
                if valid:
                    replay_bytes = candidate_bytes
                    chosen_url = candidate_url
                    chosen_owner = candidate_owner
                    chosen_validation_mode = mode
                    attempt_debug.append(
                        {
                            "url": candidate_url,
                            "owner": str(candidate_owner or ""),
                            "result": "ok",
                            "mode": mode,
                        }
                    )
                    break
                last_error = (
                    "Downloaded file is not a valid replay payload "
                    f"({reason or 'corrupt/incomplete'})."
                )
                attempt_debug.append(
                    {
                        "url": candidate_url,
                        "owner": str(candidate_owner or ""),
                        "result": "invalid_payload",
                        "error": reason,
                    }
                )

            if replay_bytes is None or chosen_url is None:
                failed += 1
                if debug:
                    debug_events.append(
                        {
                            "match_id": mid,
                            "event": "download_failed",
                            "attempts": attempt_debug,
                            "error": last_error or "",
                        }
                    )
                imported_rows.append(
                    {
                        "match_id": mid,
                        "status": "error",
                        "map_name": match.map_name,
                        "players": ", ".join(f"{p.name} ({p.side})" for p in participants),
                        "replay_url": selected_links[0][0],
                        "error": last_error or "No valid replay URL could be downloaded.",
                        "debug_attempts": attempt_debug,
                    }
                )
                continue

            owner_slug = _slug(chosen_owner or selected_links[0][1] or "unknown")
            file_name = f"match_{mid}_{owner_slug}_{map_slug}.rep"
            out_path = out_dir / file_name
            out_path.write_bytes(replay_bytes)
            downloaded += 1
            if debug:
                debug_events.append(
                    {
                        "match_id": mid,
                        "event": "download_ok",
                        "mode": chosen_validation_mode,
                        "saved_path": str(out_path),
                    }
                )
            imported_rows.append(
                {
                    "match_id": mid,
                    "status": "downloaded",
                    "validation_mode": chosen_validation_mode,
                    "map_name": match.map_name,
                    "players": ", ".join(f"{p.name} ({p.side})" for p in participants),
                    "saved_path": str(out_path),
                    "replay_url": chosen_url,
                    "size_bytes": len(replay_bytes),
                    "debug_attempts": attempt_debug,
                }
            )
        except Exception as exc:
            failed += 1
            if debug:
                debug_events.append(
                    {
                        "match_id": mid,
                        "event": "download_exception",
                        "error": str(exc),
                    }
                )
            imported_rows.append(
                {
                    "match_id": mid,
                    "status": "error",
                    "map_name": match.map_name,
                    "players": ", ".join(f"{p.name} ({p.side})" for p in participants),
                    "replay_url": selected_links[0][0],
                    "error": f"Download failed: {exc}",
                }
            )
            logger.exception("Replay import failed for match %s", mid)

    return {
        "provider": "playgenerals.online",
        "search_backend": "gomatch-index" if indexed_hits else "matchhistory-scrape",
        "output_dir": str(out_dir),
        "scanned_matches": scanned,
        "matched_filters": matched,
        "downloaded": downloaded,
        "skipped_existing": skipped_existing,
        "failed": failed,
        "rows": imported_rows,
        "debug": debug,
        "debug_events": debug_events,
    }
