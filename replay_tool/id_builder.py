from __future__ import annotations

from collections import OrderedDict
import json
from pathlib import Path
import re
import struct
from typing import Iterator


class _FsNode:
    __slots__ = ("dirs", "files")

    def __init__(self) -> None:
        self.dirs: OrderedDict[str, tuple[str, _FsNode]] = OrderedDict()
        self.files: OrderedDict[str, tuple[str, str]] = OrderedDict()


def _iter_big_files(directory: Path) -> Iterator[Path]:
    entries = list(directory.iterdir())

    def sort_key(entry: Path) -> tuple[int, int, str]:
        name = entry.stem
        bucket = 0
        if name.lower().endswith("zh"):
            bucket = 1
        if name.lower().startswith("patch"):
            bucket = 2
        # OpenSAGE behavior: ZH_Generals paths loaded first.
        zh_generals_priority = 0 if "ZH_Generals" in str(entry) else 1
        return zh_generals_priority, bucket, str(entry).lower()

    for entry in sorted(entries, key=sort_key):
        if entry.is_dir():
            yield from _iter_big_files(entry)
        elif entry.suffix.lower() == ".big":
            yield entry


def _add_virtual_file(root: _FsNode, path: str, content: str) -> None:
    parts = re.split(r"[\\/]+", path)
    node = root
    for part in parts[:-1]:
        key = part.lower()
        if key not in node.dirs:
            node.dirs[key] = (part, _FsNode())
        node = node.dirs[key][1]
    filename = parts[-1]
    node.files[filename.lower()] = (filename, content)


def _read_big_ini_entries(root: _FsNode, big_path: Path) -> None:
    with big_path.open("rb") as f:
        header = f.read(16)
        if len(header) < 16:
            return
        entry_count = struct.unpack(">I", header[8:12])[0]
        entries: list[tuple[str, int, int]] = []
        for _ in range(entry_count):
            entry_offset = struct.unpack(">I", f.read(4))[0]
            entry_size = struct.unpack(">I", f.read(4))[0]
            name_buf = bytearray()
            while True:
                b = f.read(1)
                if b == b"\x00":
                    break
                name_buf.extend(b)
            name = name_buf.decode("ascii", errors="replace")
            entries.append((name, entry_offset, entry_size))

        for name, entry_offset, entry_size in entries:
            if not name.lower().endswith(".ini"):
                continue
            current_pos = f.tell()
            f.seek(entry_offset)
            raw = f.read(entry_size)
            f.seek(current_pos)
            text = raw.decode("latin1", errors="replace")
            _add_virtual_file(root, name, text)


def _find_node(root: _FsNode, path: str) -> _FsNode | None:
    node = root
    for part in path.split("\\"):
        key = part.lower()
        if key not in node.dirs:
            return None
        node = node.dirs[key][1]
    return node


def _collect_ini_files(node: _FsNode) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for _, (filename, content) in node.files.items():
        if filename.lower().endswith(".ini"):
            files.append((filename, content))
    for _, (_, child) in node.dirs.items():
        files.extend(_collect_ini_files(child))
    return files


def _parse_object_names(ini_text: str) -> list[str]:
    result: list[str] = []
    for raw_line in ini_text.splitlines():
        line = raw_line.split(";", 1)[0].strip()
        if not line:
            continue
        if "=" in line:
            continue
        match = re.match(
            r"^(ObjectReskin|ChildObject|Object)\s+([A-Za-z0-9_:\-\.]+)(?:\s+[A-Za-z0-9_:\-\.]+)?\s*$",
            line,
            re.IGNORECASE,
        )
        if match and match.group(2) != "=":
            result.append(match.group(2))
    return result


def _parse_block_names(ini_text: str, block_keywords: tuple[str, ...]) -> list[str]:
    result: list[str] = []
    pattern = re.compile(
        r"^(" + "|".join(re.escape(k) for k in block_keywords) + r")\s+([^\s]+)",
        re.IGNORECASE,
    )
    for raw_line in ini_text.splitlines():
        line = raw_line.split(";", 1)[0].strip()
        if not line:
            continue
        if "=" in line:
            continue
        match = pattern.match(line)
        if match and match.group(2) != "=":
            result.append(match.group(2))
    return result


def build_template_lookup_from_install(install_dir: str) -> dict[int, str]:
    root_path = Path(install_dir)
    if not root_path.exists():
        raise FileNotFoundError(f"Install path not found: {install_dir}")

    virtual_root = _FsNode()
    for big_file in _iter_big_files(root_path):
        _read_big_ini_entries(virtual_root, big_file)

    default_node = _find_node(virtual_root, "Data\\INI\\Default")
    object_node = _find_node(virtual_root, "Data\\INI\\Object")
    if object_node is None:
        raise RuntimeError("Could not find Data\\INI\\Object in .big archives.")

    id_to_name: dict[int, str] = {}
    seen_names: set[str] = set()
    next_id = 1

    if default_node is not None and "object.ini" in default_node.files:
        default_object_text = default_node.files["object.ini"][1]
        for name in _parse_object_names(default_object_text):
            key = name.lower()
            if key in seen_names:
                continue
            seen_names.add(key)
            id_to_name[next_id] = name
            next_id += 1

    for _, content in _collect_ini_files(object_node):
        for name in _parse_object_names(content):
            key = name.lower()
            if key in seen_names:
                continue
            seen_names.add(key)
            id_to_name[next_id] = name
            next_id += 1

    return id_to_name


def _build_linear_id_map(
    virtual_root: _FsNode,
    init_files: list[str],
    block_keywords: tuple[str, ...],
) -> dict[int, str]:
    id_to_name: dict[int, str] = {}
    seen: set[str] = set()
    next_id = 1

    for ini_path in init_files:
        parts = ini_path.replace("/", "\\").split("\\")
        node = virtual_root
        found = True
        for part in parts[:-1]:
            key = part.lower()
            if key not in node.dirs:
                found = False
                break
            node = node.dirs[key][1]
        if not found:
            continue
        leaf = parts[-1].lower()
        if leaf not in node.files:
            continue
        content = node.files[leaf][1]
        for name in _parse_block_names(content, block_keywords):
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            id_to_name[next_id] = name
            next_id += 1
    return id_to_name


def build_full_lookup_from_install(install_dir: str) -> dict[str, dict[int, str]]:
    root_path = Path(install_dir)
    if not root_path.exists():
        raise FileNotFoundError(f"Install path not found: {install_dir}")

    virtual_root = _FsNode()
    for big_file in _iter_big_files(root_path):
        _read_big_ini_entries(virtual_root, big_file)

    template_ids = build_template_lookup_from_install(install_dir)
    upgrade_ids = _build_linear_id_map(
        virtual_root,
        ["Data\\INI\\Default\\Upgrade.ini", "Data\\INI\\Upgrade.ini"],
        ("Upgrade",),
    )
    science_ids = _build_linear_id_map(
        virtual_root,
        ["Data\\INI\\Science.ini"],
        ("Science",),
    )
    special_power_ids = _build_linear_id_map(
        virtual_root,
        ["Data\\INI\\Default\\SpecialPower.ini", "Data\\INI\\SpecialPower.ini"],
        ("SpecialPower",),
    )
    return {
        "template_ids": template_ids,
        "upgrade_ids": upgrade_ids,
        "science_ids": science_ids,
        "special_power_ids": special_power_ids,
    }


def write_lookup_json(
    id_to_name: dict[int, str] | dict[str, dict[int, str]],
    output_path: str = "replay_tool/id_lookup.json",
) -> None:
    if "template_ids" in id_to_name:  # type: ignore[operator]
        full = id_to_name  # type: ignore[assignment]
        payload = {
            key: {str(k): v for k, v in sorted(value.items())}
            for key, value in full.items()  # type: ignore[union-attr]
        }
    else:
        payload = {"template_ids": {str(k): v for k, v in sorted(id_to_name.items())}}  # type: ignore[arg-type]
    payload["_meta"] = {"id_offset": 0}
    Path(output_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
