from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
import struct
import sys
from typing import Any


class ReplayParseError(Exception):
    pass


ORDER_TYPE_NAMES = {
    27: "EndGame",
    1001: "SetSelection",
    1002: "SelectAcrossScreen",
    1003: "ClearSelection",
    1004: "Deselect",
    1006: "CreateGroup0",
    1007: "CreateGroup1",
    1008: "CreateGroup2",
    1009: "CreateGroup3",
    1010: "CreateGroup4",
    1011: "CreateGroup5",
    1012: "CreateGroup6",
    1013: "CreateGroup7",
    1014: "CreateGroup8",
    1015: "CreateGroup9",
    1016: "SelectGroup0",
    1017: "SelectGroup1",
    1018: "SelectGroup2",
    1019: "SelectGroup3",
    1020: "SelectGroup4",
    1021: "SelectGroup5",
    1022: "SelectGroup6",
    1023: "SelectGroup7",
    1024: "SelectGroup8",
    1025: "SelectGroup9",
    1038: "UseWeapon",
    1039: "SnipeVehicle",
    1040: "SpecialPower",
    1041: "SpecialPowerAtLocation",
    1042: "SpecialPowerAtObject",
    1043: "SetRallyPoint",
    1044: "PurchaseScience",
    1045: "BeginUpgrade",
    1046: "CancelUpgrade",
    1047: "CreateUnit",
    1048: "CancelUnit",
    1049: "BuildObject",
    1051: "CancelBuild",
    1052: "Sell",
    1053: "ExitContainer",
    1054: "Evacuate",
    1057: "CombatDrop",
    1058: "DrawBoxSelection",
    1059: "AttackObject",
    1060: "ForceAttackObject",
    1061: "ForceAttackGround",
    1062: "RepairVehicle",
    1064: "RepairStructure",
    1065: "ResumeBuild",
    1066: "Enter",
    1067: "GatherDumpSupplies",
    1068: "MoveTo",
    1069: "AttackMove",
    1071: "AddWaypoint",
    1072: "GuardMode",
    1074: "StopMoving",
    1075: "Scatter",
    1076: "HackInternet",
    1077: "Cheer",
    1078: "ToggleOvercharge",
    1079: "SelectWeapon",
    1086: "DirectParticleCannon",
    1092: "SetCameraPosition",
    1094: "ToggleFormationMode",
    1095: "Checksum",
    1096: "SelectClearMines",
    1097: "Unknown1097",
}

ORDER_DISPLAY_LABELS = {
    "CreateUnit": "Train Unit",
    "BuildObject": "Build Structure",
    "BeginUpgrade": "Start Upgrade",
    "CancelUpgrade": "Cancel Upgrade",
    "CancelUnit": "Cancel Unit",
    "SetRallyPoint": "Set Rally Point",
    "MoveTo": "Move",
    "AttackObject": "Attack Unit/Building",
    "ForceAttackObject": "Force Attack Unit/Building",
    "ForceAttackGround": "Force Attack Ground",
    "AttackMove": "Attack Move",
    "GuardMode": "Guard",
    "Enter": "Enter Transport/Building",
    "Evacuate": "Evacuate",
    "Sell": "Sell Structure",
    "GatherDumpSupplies": "Collect/Return Supplies",
    "PurchaseScience": "Buy General Point",
    "SpecialPower": "Use General Power",
    "SpecialPowerAtLocation": "Use Power (Location)",
    "SpecialPowerAtObject": "Use Power (Target)",
    "SelectWeapon": "Switch Weapon Mode",
    "ResumeBuild": "Resume Construction",
    "RepairStructure": "Repair Structure",
    "RepairVehicle": "Repair Vehicle",
}

NOISE_ORDER_TYPES = {
    "Checksum",
    "SetCameraPosition",
    "DrawBoxSelection",
    "ClearSelection",
    "SetSelection",
    "SelectAcrossScreen",
    "Deselect",
    "Unknown1097",
    "Unknown1093",
}

MACRO_ORDER_TYPES = {
    "BuildObject",
    "CreateUnit",
    "BeginUpgrade",
    "PurchaseScience",
    "SetRallyPoint",
}
MICRO_ORDER_TYPES = {
    "MoveTo",
    "AttackObject",
    "ForceAttackObject",
    "ForceAttackGround",
    "AttackMove",
    "GuardMode",
    "UseWeapon",
    "SpecialPower",
    "SpecialPowerAtLocation",
    "SpecialPowerAtObject",
    "SelectWeapon",
    "SnipeVehicle",
    "Scatter",
}
ECON_ORDER_TYPES = {
    "GatherDumpSupplies",
    "Sell",
    "HackInternet",
    "ResumeBuild",
}


@dataclass
class ReplayHeader:
    start_time_unix: int
    end_time_unix: int
    num_timecodes: int
    filename: str
    version: str
    build_date: str
    version_minor: int
    version_major: int
    metadata_raw: str
    game_speed: int


@dataclass
class ReplayChunk:
    timecode: int
    order_type: int
    order_name: str
    player_number: int
    arguments: list[dict[str, Any]]


def _read_exact(stream: io.BufferedReader, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise ReplayParseError(f"Unexpected EOF while reading {size} bytes.")
    return data


def _read_u8(stream: io.BufferedReader) -> int:
    return struct.unpack("<B", _read_exact(stream, 1))[0]


def _read_u16(stream: io.BufferedReader) -> int:
    return struct.unpack("<H", _read_exact(stream, 2))[0]


def _read_u32(stream: io.BufferedReader) -> int:
    return struct.unpack("<I", _read_exact(stream, 4))[0]


def _read_i32(stream: io.BufferedReader) -> int:
    return struct.unpack("<i", _read_exact(stream, 4))[0]


def _read_f32(stream: io.BufferedReader) -> float:
    return struct.unpack("<f", _read_exact(stream, 4))[0]


def _read_bool(stream: io.BufferedReader) -> bool:
    value = _read_u8(stream)
    if value not in (0, 1):
        raise ReplayParseError(f"Invalid boolean value: {value}")
    return bool(value)


def _read_utf16le_null_terminated(stream: io.BufferedReader) -> str:
    chars: list[str] = []
    while True:
        raw = _read_exact(stream, 2)
        codepoint = struct.unpack("<H", raw)[0]
        if codepoint == 0:
            return "".join(chars)
        chars.append(chr(codepoint))


def _read_ascii_null_terminated(stream: io.BufferedReader) -> str:
    buf = bytearray()
    while True:
        b = _read_exact(stream, 1)
        if b == b"\x00":
            return bytes(buf).decode("ascii", errors="replace")
        buf.extend(b)


def _parse_metadata(metadata_raw: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "map_file": None,
        "map_crc": None,
        "map_size": None,
        "starting_credits": None,
        "slots": [],
    }
    if not metadata_raw:
        return result

    for entry in [p for p in metadata_raw.split(";") if p]:
        if "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        if key == "M" and len(value) >= 2:
            result["map_file"] = value[2:]
        elif key == "MC":
            try:
                result["map_crc"] = int(value, 16)
            except ValueError:
                pass
        elif key == "MS":
            try:
                result["map_size"] = int(value)
            except ValueError:
                pass
        elif key == "SC":
            try:
                result["starting_credits"] = int(value)
            except ValueError:
                pass
        elif key == "S":
            slots = [s for s in value.split(":") if s]
            result["slots"] = [_parse_slot(s) for s in slots]
    return result


def _parse_slot(raw: str) -> dict[str, Any]:
    if not raw:
        return {"slot_type": "empty"}

    slot_kind = raw[0]
    if slot_kind in {"X", "O"}:
        return {"slot_type": "empty"}

    if slot_kind == "H":
        parts = raw.split(",")
        return {
            "slot_type": "human",
            "name": parts[0][1:] if parts else "Unknown",
            "color": _safe_int(parts, 4),
            "faction": _safe_int(parts, 5),
            "start_position": _safe_int(parts, 6),
            "team": _safe_int(parts, 7),
        }

    if slot_kind == "C":
        diff_map = {"E": "easy", "M": "medium", "H": "hard"}
        parts = raw.split(",")
        return {
            "slot_type": "computer",
            "difficulty": diff_map.get(raw[1:2], "unknown"),
            "color": _safe_int(parts, 1),
            "faction": _safe_int(parts, 2),
            "start_position": _safe_int(parts, 3),
            "team": _safe_int(parts, 4),
        }

    return {"slot_type": "unknown", "raw": raw}


def _safe_int(parts: list[str], index: int) -> int | None:
    if index >= len(parts):
        return None
    try:
        return int(parts[index])
    except ValueError:
        return None


def parse_replay_bytes(data: bytes) -> tuple[ReplayHeader, dict[str, Any], list[ReplayChunk]]:
    stream = io.BytesIO(data)
    header_tag = _read_exact(stream, 6)
    if header_tag != b"GENREP":
        raise ReplayParseError("Only Generals/Zero Hour GENREP replay files are supported.")

    header = ReplayHeader(
        start_time_unix=_read_u32(stream),
        end_time_unix=_read_u32(stream),
        num_timecodes=_read_u16(stream),
        filename="",
        version="",
        build_date="",
        version_minor=0,
        version_major=0,
        metadata_raw="",
        game_speed=0,
    )

    _read_exact(stream, 12)
    header.filename = _read_utf16le_null_terminated(stream)
    _read_exact(stream, 16)
    header.version = _read_utf16le_null_terminated(stream)
    header.build_date = _read_utf16le_null_terminated(stream)
    header.version_minor = _read_u16(stream)
    header.version_major = _read_u16(stream)
    _read_exact(stream, 8)
    header.metadata_raw = _read_ascii_null_terminated(stream)
    _read_u16(stream)
    _read_u32(stream)
    _read_u32(stream)
    _read_u32(stream)
    header.game_speed = _read_u32(stream)

    metadata = _parse_metadata(header.metadata_raw)
    chunks: list[ReplayChunk] = []

    while stream.tell() < len(data):
        timecode = _read_u32(stream)
        order_type = _read_u32(stream)
        player_number = _read_u32(stream)
        unique_arg_types = _read_u8(stream)

        arg_specs: list[tuple[int, int]] = []
        for _ in range(unique_arg_types):
            arg_type = _read_u8(stream)
            count = _read_u8(stream)
            arg_specs.append((arg_type, count))

        arguments: list[dict[str, Any]] = []
        for arg_type, count in arg_specs:
            for _ in range(count):
                if arg_type in (0, 4, 5, 9):
                    arguments.append({"type": arg_type, "value": _read_i32(stream)})
                elif arg_type == 1:
                    arguments.append({"type": arg_type, "value": _read_f32(stream)})
                elif arg_type == 2:
                    arguments.append({"type": arg_type, "value": _read_bool(stream)})
                elif arg_type == 3:
                    arguments.append({"type": arg_type, "value": _read_u32(stream)})
                elif arg_type == 6:
                    arguments.append(
                        {
                            "type": arg_type,
                            "value": (_read_f32(stream), _read_f32(stream), _read_f32(stream)),
                        }
                    )
                elif arg_type == 7:
                    arguments.append({"type": arg_type, "value": (_read_i32(stream), _read_i32(stream))})
                elif arg_type == 8:
                    arguments.append(
                        {
                            "type": arg_type,
                            "value": (_read_i32(stream), _read_i32(stream), _read_i32(stream), _read_i32(stream)),
                        }
                    )
                elif arg_type == 10:
                    arguments.append({"type": arg_type, "value": struct.unpack("<h", _read_exact(stream, 2))[0]})
                else:
                    raise ReplayParseError(f"Unknown argument type: {arg_type}")

        chunks.append(
            ReplayChunk(
                timecode=timecode,
                order_type=order_type,
                order_name=ORDER_TYPE_NAMES.get(order_type, f"Unknown{order_type}"),
                player_number=player_number,
                arguments=arguments,
            )
        )

    return header, metadata, chunks


def parse_replay_preview_bytes(data: bytes) -> tuple[ReplayHeader, dict[str, Any]]:
    stream = io.BytesIO(data)
    header_tag = _read_exact(stream, 6)
    if header_tag != b"GENREP":
        raise ReplayParseError("Only Generals/Zero Hour GENREP replay files are supported.")

    header = ReplayHeader(
        start_time_unix=_read_u32(stream),
        end_time_unix=_read_u32(stream),
        num_timecodes=_read_u16(stream),
        filename="",
        version="",
        build_date="",
        version_minor=0,
        version_major=0,
        metadata_raw="",
        game_speed=0,
    )

    _read_exact(stream, 12)
    header.filename = _read_utf16le_null_terminated(stream)
    _read_exact(stream, 16)
    header.version = _read_utf16le_null_terminated(stream)
    header.build_date = _read_utf16le_null_terminated(stream)
    header.version_minor = _read_u16(stream)
    header.version_major = _read_u16(stream)
    _read_exact(stream, 8)
    header.metadata_raw = _read_ascii_null_terminated(stream)
    _read_u16(stream)
    _read_u32(stream)
    _read_u32(stream)
    _read_u32(stream)
    header.game_speed = _read_u32(stream)

    metadata = _parse_metadata(header.metadata_raw)
    return header, metadata


def _player_name(player_number: int, metadata: dict[str, Any]) -> str:
    idx = player_number - 1
    slots = metadata.get("slots", [])
    if 0 <= idx < len(slots):
        slot = slots[idx]
        if slot.get("slot_type") == "human" and slot.get("name"):
            return slot["name"]
        if slot.get("slot_type") == "computer":
            return f"AI ({slot.get('difficulty', 'unknown')})"
    return f"Player {player_number}"


def _format_utc(unix_time: int) -> str:
    return datetime.fromtimestamp(unix_time, tz=timezone.utc).isoformat()


def _clock_from_timecode(timecode: int) -> str:
    total_seconds = int(round(timecode / 30.0))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def _format_arg_value(value: Any) -> str:
    if isinstance(value, tuple):
        return "(" + ", ".join(f"{x:.1f}" if isinstance(x, float) else str(x) for x in value) + ")"
    return str(value)


def _extract_int_arg(chunk: ReplayChunk, index: int) -> int | None:
    int_args = [arg["value"] for arg in chunk.arguments if arg.get("type") in (0, 4, 5, 9)]
    if 0 <= index < len(int_args):
        return int(int_args[index])
    return None


def _extract_objid_arg(chunk: ReplayChunk, index: int) -> int | None:
    obj_args = [arg["value"] for arg in chunk.arguments if arg.get("type") == 3]
    if 0 <= index < len(obj_args):
        return int(obj_args[index])
    return None


def _humanize_name(raw: str | None) -> str | None:
    if not raw:
        return None
    faction_prefix = {
        "Lazr": "Laser",
        "AirF": "Air Force",
        "SupW": "Super Weapon",
        "Nuke": "Nuke",
        "Infa": "Infantry",
        "Tank": "Tank",
        "Demo": "Demo",
        "Chem": "Toxin",
        "Slth": "Stealth",
        "Boss": "Boss",
    }
    parts = raw.split("_")
    prefix = None
    if parts and parts[0] in faction_prefix:
        prefix = faction_prefix[parts[0]]
        parts = parts[1:]
    txt = " ".join(parts) if parts else raw
    txt = re.sub(r"([a-z])([A-Z])", r"\1 \2", txt)
    txt = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    if prefix:
        return f"{txt} [{prefix}]"
    return txt


def _resolve_with_offset(id_value: int | None, name_map: dict[str, str], id_offset: int) -> str | None:
    if id_value is None:
        return None
    shifted = name_map.get(str(id_value + id_offset))
    direct = name_map.get(str(id_value))
    return shifted or direct


def _timeline_detail(
    chunk: ReplayChunk,
    template_map: dict[str, str],
    upgrade_map: dict[str, str],
    science_map: dict[str, str],
    power_map: dict[str, str],
    id_offset: int,
) -> tuple[str, dict[str, Any]]:
    extra: dict[str, Any] = {}
    if chunk.order_name == "BuildObject":
        template_id = _extract_int_arg(chunk, 0)
        pos_args = [arg["value"] for arg in chunk.arguments if arg.get("type") == 6]
        if pos_args:
            x, y, _ = pos_args[0]
            extra["position"] = {"x": round(float(x), 2), "y": round(float(y), 2)}
        if template_id is None:
            return "", extra
        name = _resolve_with_offset(template_id, template_map, id_offset)
        extra["template_id"] = template_id
        extra["template_name"] = name
        extra["template_name_human"] = _humanize_name(name)
        if pos_args:
            x, y, _ = pos_args[0]
            return f"template_id={template_id}, position=({x:.1f}, {y:.1f})", extra
        return f"template_id={template_id}", extra
    if chunk.order_name == "CreateUnit":
        template_id = _extract_int_arg(chunk, 0)
        queue_index = _extract_int_arg(chunk, 1)
        if template_id is not None:
            name = _resolve_with_offset(template_id, template_map, id_offset)
            extra["template_id"] = template_id
            extra["template_name"] = name
            extra["template_name_human"] = _humanize_name(name)
        if template_id is None and queue_index is None:
            return "", extra
        if queue_index is None:
            return f"template_id={template_id}", extra
        return f"template_id={template_id}, queue_index={queue_index}", extra
    if chunk.order_name == "BeginUpgrade":
        upgrade_id = _extract_int_arg(chunk, 0)
        if upgrade_id is None:
            return "", extra
        name = _resolve_with_offset(upgrade_id, upgrade_map, id_offset)
        extra["upgrade_id"] = upgrade_id
        extra["upgrade_name"] = name
        extra["upgrade_name_human"] = _humanize_name(name)
        return f"upgrade_id={upgrade_id}", extra
    if chunk.order_name == "CancelUnit":
        queue_index = _extract_int_arg(chunk, 0)
        return (f"queue_index={queue_index}" if queue_index is not None else ""), extra
    if chunk.order_name in {"MoveTo", "AttackMove", "ForceAttackGround", "GuardMode"}:
        pos_args = [arg["value"] for arg in chunk.arguments if arg.get("type") == 6]
        if pos_args:
            x, y, _ = pos_args[0]
            extra["position"] = {"x": round(float(x), 2), "y": round(float(y), 2)}
            return f"position=({x:.1f}, {y:.1f})", extra
        return "", extra
    if chunk.order_name in {"AttackObject", "ForceAttackObject", "Enter", "RepairStructure", "RepairVehicle"}:
        obj_id = _extract_objid_arg(chunk, 0)
        return (f"target_object_id={obj_id}" if obj_id is not None else ""), extra
    if chunk.order_name == "SetRallyPoint":
        obj_id = _extract_objid_arg(chunk, 0)
        pos_args = [arg["value"] for arg in chunk.arguments if arg.get("type") == 6]
        if pos_args:
            x, y, _ = pos_args[0]
            extra["position"] = {"x": round(float(x), 2), "y": round(float(y), 2)}
            if obj_id is not None:
                return f"producer_object_id={obj_id}, position=({x:.1f}, {y:.1f})", extra
            return f"position=({x:.1f}, {y:.1f})", extra
        return (f"producer_object_id={obj_id}" if obj_id is not None else ""), extra
    if chunk.order_name in {"SpecialPower", "SpecialPowerAtLocation", "SpecialPowerAtObject"}:
        power_id = _extract_int_arg(chunk, 0)
        if power_id is not None:
            name = _resolve_with_offset(power_id, power_map, id_offset)
            extra["power_id"] = power_id
            extra["power_name"] = name
            extra["power_name_human"] = _humanize_name(name)
        if chunk.order_name == "SpecialPowerAtLocation":
            pos_args = [arg["value"] for arg in chunk.arguments if arg.get("type") == 6]
            if pos_args:
                x, y, _ = pos_args[0]
                extra["position"] = {"x": round(float(x), 2), "y": round(float(y), 2)}
                return f"power_id={power_id}, position=({x:.1f}, {y:.1f})", extra
        if chunk.order_name == "SpecialPowerAtObject":
            target_obj = _extract_objid_arg(chunk, 0)
            return f"power_id={power_id}, target_object_id={target_obj}", extra
        return f"power_id={power_id}", extra
    if chunk.order_name == "PurchaseScience":
        science_id = _extract_int_arg(chunk, 0)
        if science_id is not None:
            name = _resolve_with_offset(science_id, science_map, id_offset)
            extra["science_id"] = science_id
            extra["science_name"] = name
            extra["science_name_human"] = _humanize_name(name)
            return f"science_id={science_id}", extra
        return "", extra
    if chunk.order_name == "ResumeBuild":
        target_obj = _extract_objid_arg(chunk, 0)
        return (f"target_object_id={target_obj}" if target_obj is not None else ""), extra
    return ", ".join(
        f"t{arg['type']}={_format_arg_value(arg['value'])}" for arg in chunk.arguments[:4]
    ), extra


def _extract_template_id(chunk: ReplayChunk) -> int | None:
    if chunk.order_name in {"BuildObject", "CreateUnit"}:
        return _extract_int_arg(chunk, 0)
    return None


def _load_name_lookup() -> dict[str, Any]:
    candidates: list[Path] = []
    # Normal project layout.
    candidates.append(Path("replay_tool") / "id_lookup.json")
    # Next to executable / current working dir.
    candidates.append(Path.cwd() / "id_lookup.json")
    # Frozen apps (PyInstaller).
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "replay_tool" / "id_lookup.json")
    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    if exe_dir:
        candidates.append(exe_dir / "id_lookup.json")
        candidates.append(exe_dir / "replay_tool" / "id_lookup.json")

    lookup_path = next((p for p in candidates if p.exists()), None)
    if lookup_path is None:
        return {"template_ids": {}, "upgrade_ids": {}, "science_ids": {}, "special_power_ids": {}, "id_offset": 0}
    try:
        payload = json.loads(lookup_path.read_text(encoding="utf-8"))
    except Exception:
        return {"template_ids": {}, "upgrade_ids": {}, "science_ids": {}, "special_power_ids": {}, "id_offset": 0}
    out: dict[str, Any] = {}
    for key in ("template_ids", "upgrade_ids", "science_ids", "special_power_ids"):
        value = payload.get(key, {})
        if isinstance(value, dict):
            out[key] = {str(k): str(v) for k, v in value.items()}
        else:
            out[key] = {}
    out["id_offset"] = int(payload.get("_meta", {}).get("id_offset", 0))
    return out


def analyze_replay_bytes(data: bytes) -> dict[str, Any]:
    header, metadata, chunks = parse_replay_bytes(data)
    if not chunks:
        raise ReplayParseError("Replay contains no command chunks.")

    max_timecode = max(chunk.timecode for chunk in chunks)
    tick_seconds = max_timecode / 30.0
    header_seconds = max(0, header.end_time_unix - header.start_time_unix)
    duration_seconds = float(header_seconds if header_seconds > 0 else tick_seconds)
    duration_minutes = max(duration_seconds / 60.0, 0.01)

    per_player: dict[int, list[ReplayChunk]] = defaultdict(list)
    for chunk in chunks:
        per_player[chunk.player_number].append(chunk)

    player_reports = []
    lookup = _load_name_lookup()
    template_name_lookup = lookup.get("template_ids", {})
    upgrade_name_lookup = lookup.get("upgrade_ids", {})
    science_name_lookup = lookup.get("science_ids", {})
    power_name_lookup = lookup.get("special_power_ids", {})
    id_offset = int(lookup.get("id_offset", 1))
    unresolved_template_ids: Counter[int] = Counter()
    resolved_template_hits: Counter[str] = Counter()
    for player_number, player_chunks in sorted(per_player.items()):
        order_counter = Counter(chunk.order_name for chunk in player_chunks)
        meaningful_order_counter = Counter(
            name for name in order_counter.elements() if name not in NOISE_ORDER_TYPES
        )
        macro = sum(order_counter.get(name, 0) for name in MACRO_ORDER_TYPES)
        micro = sum(order_counter.get(name, 0) for name in MICRO_ORDER_TYPES)
        eco = sum(order_counter.get(name, 0) for name in ECON_ORDER_TYPES)
        actions = len(player_chunks)
        meaningful_actions = sum(meaningful_order_counter.values())
        apm = round(actions / duration_minutes, 1)
        effective_apm = round(meaningful_actions / duration_minutes, 1)
        timeline = []
        map_events = []
        for chunk in player_chunks:
            if chunk.order_name in NOISE_ORDER_TYPES:
                continue
            template_id = _extract_template_id(chunk)
            template_name = None
            if template_id is not None:
                template_name = _resolve_with_offset(template_id, template_name_lookup, id_offset)
                if template_name:
                    resolved_template_hits[template_name] += 1
                else:
                    unresolved_template_ids[template_id] += 1

            detail, extra = _timeline_detail(
                chunk,
                template_name_lookup,
                upgrade_name_lookup,
                science_name_lookup,
                power_name_lookup,
                id_offset,
            )

            timeline_item = {
                "timecode": chunk.timecode,
                "clock": _clock_from_timecode(chunk.timecode),
                "action": chunk.order_name,
                "label": ORDER_DISPLAY_LABELS.get(chunk.order_name, chunk.order_name),
                "detail": detail,
                "template_id": template_id,
                "template_name": template_name,
                "template_name_human": _humanize_name(template_name),
                **extra,
            }
            timeline.append(timeline_item)

            pos = timeline_item.get("position")
            if isinstance(pos, dict) and "x" in pos and "y" in pos:
                action = str(timeline_item.get("action", ""))
                kind = "build" if action == "BuildObject" else "move"
                map_events.append(
                    {
                        "timecode": timeline_item["timecode"],
                        "clock": timeline_item["clock"],
                        "kind": kind,
                        "action": action,
                        "label": timeline_item["label"],
                        "x": pos["x"],
                        "y": pos["y"],
                        "template_name": timeline_item.get("template_name"),
                        "template_name_human": timeline_item.get("template_name_human"),
                    }
                )

        player_reports.append(
            {
                "player_number": player_number,
                "player_name": _player_name(player_number, metadata),
                "actions": actions,
                "estimated_apm": apm,
                "meaningful_actions": meaningful_actions,
                "effective_apm": effective_apm,
                "macro_actions": macro,
                "micro_actions": micro,
                "economy_actions": eco,
                "top_orders": [
                    {"order": name, "count": count}
                    for name, count in order_counter.most_common(10)
                ],
                "top_meaningful_orders": [
                    {"order": name, "count": count}
                    for name, count in meaningful_order_counter.most_common(10)
                ],
                "timeline": timeline,
                "map_events": map_events,
            }
        )

    global_orders = Counter(chunk.order_name for chunk in chunks).most_common(20)
    meaningful_global = Counter(
        chunk.order_name for chunk in chunks if chunk.order_name not in NOISE_ORDER_TYPES
    ).most_common(20)
    meaningful_total = sum(count for _, count in meaningful_global)

    return {
        "replay": {
            "file_name_in_header": header.filename,
            "version": header.version,
            "build_date": header.build_date,
            "start_time_utc": _format_utc(header.start_time_unix),
            "end_time_utc": _format_utc(header.end_time_unix),
            "duration_seconds_estimate": round(duration_seconds, 2),
            "duration_seconds_by_timecode": round(tick_seconds, 2),
            "num_timecodes_header": header.num_timecodes,
            "max_timecode_seen": max_timecode,
            "game_speed": header.game_speed,
            "map_file": metadata.get("map_file"),
            "starting_credits": metadata.get("starting_credits"),
            "total_actions": len(chunks),
            "meaningful_actions_total": meaningful_total,
        },
        "players": player_reports,
        "top_orders_overall": [{"order": name, "count": count} for name, count in global_orders],
        "top_meaningful_orders_overall": [
            {"order": name, "count": count} for name, count in meaningful_global
        ],
        "id_resolution": {
            "lookup_file": "replay_tool/id_lookup.json",
            "id_offset_applied": id_offset,
            "resolved_templates": [
                {"name": name, "count": count}
                for name, count in resolved_template_hits.most_common()
            ],
            "unresolved_template_ids": [
                {"template_id": tid, "count": count}
                for tid, count in unresolved_template_ids.most_common()
            ],
        },
        "notes": [
            "Replay contains player input commands, not all in-game events (damage, deaths, economy ticks).",
            "Meaningful actions exclude selection/camera/checksum noise.",
            "APM is estimated from replay duration.",
            "ID mapping applies offset for replay/internal index compatibility.",
            "Template names are resolved from replay_tool/id_lookup.json when available.",
            "Unknown orders are shown as Unknown<id> and still counted.",
        ],
    }


def analyze_file_to_json(path: str) -> str:
    with open(path, "rb") as f:
        report = analyze_replay_bytes(f.read())
    return json.dumps(report, indent=2)
