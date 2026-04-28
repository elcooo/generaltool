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


def _dump(out_dir: Path, names, getter) -> tuple[int, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    for name in sorted(names):
        uri = getter(name)
        if not uri or not uri.startswith("data:image/png;base64,"):
            skipped += 1
            continue
        b64 = uri.split(",", 1)[1]
        (out_dir / f"{_safe_filename(name)}.png").write_bytes(base64.b64decode(b64))
        written += 1
    return written, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump all template/science/upgrade/power icons to replay_tool/icons/.")
    parser.add_argument("--install-dir", default=None, help="Zero Hour install directory (auto-detected if omitted)")
    args = parser.parse_args()

    install_dir = args.install_dir or _guess_install_dir()
    if not install_dir:
        raise SystemExit("Could not locate Zero Hour install. Pass --install-dir explicitly.")

    print(f"Using install dir: {install_dir}")
    provider = IconProvider(install_dir)
    ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    tpl_w, tpl_s = _dump(
        ICON_CACHE_DIR,
        provider._template_to_portrait.keys(),
        provider.get_icon_data_uri,
    )
    print(f"Templates: wrote {tpl_w}, skipped {tpl_s}")

    sci_w, sci_s = _dump(
        ICON_CACHE_DIR / "sciences",
        provider._science_to_image.keys(),
        provider.get_science_icon_data_uri,
    )
    print(f"Sciences: wrote {sci_w}, skipped {sci_s}")

    up_w, up_s = _dump(
        ICON_CACHE_DIR / "upgrades",
        provider._upgrade_to_image.keys(),
        provider.get_upgrade_icon_data_uri,
    )
    print(f"Upgrades: wrote {up_w}, skipped {up_s}")

    pow_w, pow_s = _dump(
        ICON_CACHE_DIR / "powers",
        provider._power_to_image.keys(),
        provider.get_power_icon_data_uri,
    )
    print(f"Powers: wrote {pow_w}, skipped {pow_s}")


if __name__ == "__main__":
    main()
