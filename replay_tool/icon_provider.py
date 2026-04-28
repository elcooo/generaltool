from __future__ import annotations

import base64
from dataclasses import dataclass
import io
import os
from pathlib import Path
import re
import struct
from typing import Any

from PIL import Image


DEFAULT_INSTALL_DIR = (
    r"C:\Program Files (x86)\R.G. Mechanics\Command and Conquer - Generals\Command and Conquer Generals Zero Hour"
)


@dataclass
class _MappedImage:
    texture: str
    left: int
    top: int
    right: int
    bottom: int
    status: str


class _BigReader:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._index: dict[str, tuple[int, int, str]] = {}
        self._read_index()

    def _read_index(self) -> None:
        with self.path.open("rb") as f:
            header = f.read(16)
            if len(header) < 16:
                return
            entry_count = struct.unpack(">I", header[8:12])[0]
            for _ in range(entry_count):
                offset = struct.unpack(">I", f.read(4))[0]
                size = struct.unpack(">I", f.read(4))[0]
                name_buf = bytearray()
                while True:
                    b = f.read(1)
                    if b == b"\x00":
                        break
                    name_buf.extend(b)
                name = name_buf.decode("ascii", errors="replace")
                self._index[name.lower()] = (offset, size, name)

    def iter_names(self) -> list[str]:
        return [v[2] for v in self._index.values()]

    def read_bytes(self, name: str) -> bytes | None:
        rec = self._index.get(name.lower())
        if rec is None:
            return None
        offset, size, _ = rec
        with self.path.open("rb") as f:
            f.seek(offset)
            return f.read(size)

    def find_by_basename(self, basename: str) -> str | None:
        low = basename.lower()
        for key, (_, _, original) in self._index.items():
            if key.endswith("\\" + low) or key.endswith("/" + low) or key == low:
                return original
        return None


class IconProvider:
    def __init__(self, install_dir: str) -> None:
        self.install_dir = Path(install_dir)
        self.inizh = _BigReader(self.install_dir / "INIZH.big")
        self.englishzh = _BigReader(self.install_dir / "EnglishZH.big")
        self.windowzh = _BigReader(self.install_dir / "WindowZH.big") if (self.install_dir / "WindowZH.big").exists() else None
        self._mapped_images = self._load_mapped_images()
        self._template_to_portrait = self._load_template_portraits()
        (
            self._science_to_image,
            self._upgrade_to_image,
            self._power_to_image,
        ) = self._load_command_button_images()
        self._texture_path_cache: dict[str, str | None] = {}
        self._icon_cache: dict[str, str | None] = {}

    def _load_mapped_images(self) -> dict[str, _MappedImage]:
        result: dict[str, _MappedImage] = {}
        for name in self.inizh.iter_names():
            low = name.lower()
            if "mappedimages" not in low or not low.endswith(".ini"):
                continue
            raw = self.inizh.read_bytes(name)
            if raw is None:
                continue
            text = raw.decode("latin1", errors="replace")
            lines = text.splitlines()
            i = 0
            while i < len(lines):
                m = re.match(r"^\s*MappedImage\s+([^\s]+)", lines[i], re.IGNORECASE)
                if not m:
                    i += 1
                    continue
                mapped_name = m.group(1)
                i += 1
                texture = None
                left = top = right = bottom = None
                status = "NONE"
                while i < len(lines):
                    line = lines[i].split(";", 1)[0].strip()
                    i += 1
                    if not line:
                        continue
                    if re.match(r"^End$", line, re.IGNORECASE):
                        break
                    mt = re.match(r"^Texture\s*=\s*([^\s]+)", line, re.IGNORECASE)
                    if mt:
                        texture = mt.group(1)
                        continue
                    mc = re.match(
                        r"^Coords\s*=\s*Left:(\d+)\s+Top:(\d+)\s+Right:(\d+)\s+Bottom:(\d+)",
                        line,
                        re.IGNORECASE,
                    )
                    if mc:
                        left, top, right, bottom = map(int, mc.groups())
                        continue
                    ms = re.match(r"^Status\s*=\s*([^\s]+)", line, re.IGNORECASE)
                    if ms:
                        status = ms.group(1)
                        continue
                if texture and left is not None and top is not None and right is not None and bottom is not None:
                    result[mapped_name] = _MappedImage(texture, left, top, right, bottom, status)
        return result

    def _load_template_portraits(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for name in self.inizh.iter_names():
            low = name.lower()
            if not low.startswith("data\\ini\\object\\") or not low.endswith(".ini"):
                continue
            raw = self.inizh.read_bytes(name)
            if raw is None:
                continue
            text = raw.decode("latin1", errors="replace")
            for obj_name, block in re.findall(
                r"(?ims)^\s*(?:Object|ChildObject|ObjectReskin)\s+([^\s]+)(.*?)^\s*End\s*$",
                text,
            ):
                m = re.search(r"(?im)^\s*SelectPortrait\s*=\s*([^\s;]+)", block)
                if m:
                    mapping[obj_name] = m.group(1)
        return mapping

    def _load_command_button_images(self) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        science_map: dict[str, str] = {}
        upgrade_map: dict[str, str] = {}
        power_map: dict[str, str] = {}
        for name in self.inizh.iter_names():
            low = name.lower()
            if not low.endswith("commandbutton.ini"):
                continue
            raw = self.inizh.read_bytes(name)
            if raw is None:
                continue
            text = raw.decode("latin1", errors="replace")
            for _btn_name, block in re.findall(
                r"(?ims)^\s*CommandButton\s+([^\s]+)(.*?)^\s*End\s*$",
                text,
            ):
                m_img = re.search(r"(?im)^\s*ButtonImage\s*=\s*([^\s;]+)", block)
                if not m_img:
                    continue
                image = m_img.group(1)
                m_sp = re.search(r"(?im)^\s*SpecialPower\s*=\s*([^\s;]+)", block)
                if m_sp:
                    power_map.setdefault(m_sp.group(1), image)
                m_up = re.search(r"(?im)^\s*Upgrade\s*=\s*([^\s;]+)", block)
                if m_up:
                    upgrade_map.setdefault(m_up.group(1), image)
                m_sc = re.search(r"(?im)^\s*Science\s*=\s*([^\s;]+)", block)
                if m_sc:
                    science_map.setdefault(m_sc.group(1), image)
        return science_map, upgrade_map, power_map

    def _resolve_texture_path(self, texture_name: str) -> str | None:
        if texture_name in self._texture_path_cache:
            return self._texture_path_cache[texture_name]
        found = self.englishzh.find_by_basename(texture_name)
        if found is None and self.windowzh is not None:
            found = self.windowzh.find_by_basename(texture_name)
        self._texture_path_cache[texture_name] = found
        return found

    @staticmethod
    def _apply_rotation(img: Image.Image, status: str) -> Image.Image:
        st = status.upper()
        if st == "ROTATED_90_CLOCKWISE":
            return img.transpose(Image.Transpose.ROTATE_90)
        if st == "ROTATED_90_COUNTERCLOCKWISE":
            return img.transpose(Image.Transpose.ROTATE_270)
        if st == "ROTATED_180":
            return img.transpose(Image.Transpose.ROTATE_180)
        return img

    def _render_mapped_image(self, mapped_name: str) -> str | None:
        cache_key = f"__img__:{mapped_name}"
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]
        mapped = self._mapped_images.get(mapped_name)
        if not mapped:
            self._icon_cache[cache_key] = None
            return None
        texture_entry = self._resolve_texture_path(mapped.texture)
        if not texture_entry:
            self._icon_cache[cache_key] = None
            return None
        raw = self.englishzh.read_bytes(texture_entry)
        if raw is None and self.windowzh is not None:
            raw = self.windowzh.read_bytes(texture_entry)
        if raw is None:
            self._icon_cache[cache_key] = None
            return None
        try:
            img = Image.open(io.BytesIO(raw)).convert("RGBA")
            crop = img.crop((mapped.left, mapped.top, mapped.right + 1, mapped.bottom + 1))
            crop = self._apply_rotation(crop, mapped.status)
            crop = crop.resize((28, 28), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            crop.save(out, format="PNG")
            b64 = base64.b64encode(out.getvalue()).decode("ascii")
            uri = f"data:image/png;base64,{b64}"
            self._icon_cache[cache_key] = uri
            return uri
        except Exception:
            self._icon_cache[cache_key] = None
            return None

    def get_icon_data_uri(self, template_name: str) -> str | None:
        portrait = self._template_to_portrait.get(template_name)
        if not portrait:
            return None
        return self._render_mapped_image(portrait)

    def get_science_icon_data_uri(self, science_name: str) -> str | None:
        image = self._science_to_image.get(science_name)
        if not image:
            return None
        return self._render_mapped_image(image)

    def get_upgrade_icon_data_uri(self, upgrade_name: str) -> str | None:
        image = self._upgrade_to_image.get(upgrade_name)
        if not image:
            return None
        return self._render_mapped_image(image)

    def get_power_icon_data_uri(self, power_name: str) -> str | None:
        image = self._power_to_image.get(power_name)
        if not image:
            return None
        return self._render_mapped_image(image)


_provider: IconProvider | None = None

ICON_CACHE_DIR = Path(__file__).parent / "icons"


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def _read_cached_icon(category: str, name: str) -> str | None:
    if category == "template":
        candidates = [ICON_CACHE_DIR / f"{_safe_filename(name)}.png", ICON_CACHE_DIR / "templates" / f"{_safe_filename(name)}.png"]
    else:
        candidates = [ICON_CACHE_DIR / f"{category}s" / f"{_safe_filename(name)}.png"]
    for path in candidates:
        if path.exists():
            try:
                b64 = base64.b64encode(path.read_bytes()).decode("ascii")
                return f"data:image/png;base64,{b64}"
            except Exception:
                return None
    return None


def _guess_install_dir() -> str | None:
    candidates = [
        DEFAULT_INSTALL_DIR,
        r"C:\Program Files (x86)\EA Games\Command & Conquer Generals Zero Hour",
        r"C:\Program Files\EA Games\Command & Conquer Generals Zero Hour",
        r"C:\Program Files (x86)\Origin Games\Command and Conquer Generals Zero Hour",
        r"C:\Program Files (x86)\Steam\steamapps\common\Command and Conquer Generals Zero Hour",
        r"D:\SteamLibrary\steamapps\common\Command and Conquer Generals Zero Hour",
    ]
    for c in candidates:
        p = Path(c)
        if (p / "INIZH.big").exists() and (p / "EnglishZH.big").exists():
            return c
    return None


def _get_provider() -> IconProvider | None:
    global _provider
    if _provider is not None:
        return _provider
    install_dir = os.environ.get("ZH_INSTALL_DIR") or _guess_install_dir() or DEFAULT_INSTALL_DIR
    p = Path(install_dir)
    if not (p / "INIZH.big").exists() or not (p / "EnglishZH.big").exists():
        return None
    _provider = IconProvider(install_dir)
    return _provider


_disk_cache_uri: dict[tuple[str, str], str | None] = {}


def _resolve(category: str, name: str | None, live_lookup) -> str | None:
    if not name:
        return None
    provider = _get_provider()
    if provider is not None:
        return live_lookup(provider, name)
    key = (category, name)
    if key in _disk_cache_uri:
        return _disk_cache_uri[key]
    uri = _read_cached_icon(category, name)
    _disk_cache_uri[key] = uri
    return uri


def get_template_icon_data_uri(template_name: str | None) -> str | None:
    return _resolve("template", template_name, lambda p, n: p.get_icon_data_uri(n))


def get_science_icon_data_uri(science_name: str | None) -> str | None:
    return _resolve("science", science_name, lambda p, n: p.get_science_icon_data_uri(n))


def get_upgrade_icon_data_uri(upgrade_name: str | None) -> str | None:
    return _resolve("upgrade", upgrade_name, lambda p, n: p.get_upgrade_icon_data_uri(n))


def get_power_icon_data_uri(power_name: str | None) -> str | None:
    return _resolve("power", power_name, lambda p, n: p.get_power_icon_data_uri(n))
