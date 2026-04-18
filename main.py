from __future__ import annotations

import argparse

from replay_tool.analyzer import analyze_file_to_json
from replay_tool.id_builder import build_full_lookup_from_install, write_lookup_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a Zero Hour .rep replay file.")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    analyze_parser = subparsers.add_parser("analyze", help="Analyze a replay file")
    analyze_parser.add_argument("replay", help="Path to .rep file")

    map_parser = subparsers.add_parser("build-id-map", help="Build template id->name map from game install")
    map_parser.add_argument("install_dir", help="Zero Hour install directory")
    map_parser.add_argument(
        "--out",
        default="replay_tool/id_lookup.json",
        help="Output JSON file path (default: replay_tool/id_lookup.json)",
    )

    args = parser.parse_args()
    if args.cmd == "analyze":
        print(analyze_file_to_json(args.replay))
        return

    full_map = build_full_lookup_from_install(args.install_dir)
    write_lookup_json(full_map, args.out)
    print(
        f"Wrote lookup to {args.out} "
        f"(templates={len(full_map['template_ids'])}, upgrades={len(full_map['upgrade_ids'])}, "
        f"sciences={len(full_map['science_ids'])}, powers={len(full_map['special_power_ids'])})"
    )


if __name__ == "__main__":
    main()
