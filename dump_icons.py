from __future__ import annotations

import argparse
import base64
from pathlib import Path

from replay_tool.icon_provider import (
    ICON_CACHE_DIR,
    IconProvider,
    _guess_install_dir,
    _safe_filename,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump all template icons to replay_tool/icons/ as PNGs.")
    parser.add_argument("--install-dir", default=None, help="Zero Hour install directory (auto-detected if omitted)")
    args = parser.parse_args()

    install_dir = args.install_dir or _guess_install_dir()
    if not install_dir:
        raise SystemExit("Could not locate Zero Hour install. Pass --install-dir explicitly.")

    print(f"Using install dir: {install_dir}")
    provider = IconProvider(install_dir)
    ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    templates = sorted(provider._template_to_portrait.keys())
    print(f"Found {len(templates)} templates with portraits.")

    written = 0
    skipped = 0
    for name in templates:
        uri = provider.get_icon_data_uri(name)
        if not uri or not uri.startswith("data:image/png;base64,"):
            skipped += 1
            continue
        b64 = uri.split(",", 1)[1]
        out_path = ICON_CACHE_DIR / f"{_safe_filename(name)}.png"
        out_path.write_bytes(base64.b64decode(b64))
        written += 1

    print(f"Wrote {written} icons to {ICON_CACHE_DIR}, skipped {skipped}.")


if __name__ == "__main__":
    main()
