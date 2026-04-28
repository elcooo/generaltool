from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).parent / "replay_tool" / "icons" / "actions"

# (bg color, fg color, glyph). One entry per action name (or prefix-* group).
SPECS: dict[str, tuple[str, str, str]] = {
    "MoveTo": ("#1f6fb2", "#ffffff", "→"),
    "AttackMove": ("#b42828", "#ffffff", "⚔"),
    "AttackObject": ("#b42828", "#ffffff", "✕"),
    "ForceAttackObject": ("#8a1f1f", "#ffffff", "✕"),
    "ForceAttackGround": ("#8a1f1f", "#ffffff", "✕"),
    "GuardMode": ("#5b6777", "#ffffff", "⛨"),
    "StopMoving": ("#444444", "#ffffff", "■"),
    "Scatter": ("#7a4a8a", "#ffffff", "≋"),
    "SetRallyPoint": ("#2e8b57", "#ffffff", "⚐"),
    "Sell": ("#c4572d", "#ffffff", "$"),
    "Enter": ("#0f6a8b", "#ffffff", "⤵"),
    "ExitContainer": ("#0f6a8b", "#ffffff", "⤴"),
    "Evacuate": ("#0f6a8b", "#ffffff", "⤴"),
    "CombatDrop": ("#0f6a8b", "#ffffff", "↓"),
    "RepairVehicle": ("#a07020", "#ffffff", "✚"),
    "RepairStructure": ("#a07020", "#ffffff", "✚"),
    "ResumeBuild": ("#a07020", "#ffffff", "▶"),
    "GatherDumpSupplies": ("#8b6f2a", "#ffffff", "$"),
    "HackInternet": ("#3a7d3a", "#ffffff", "@"),
    "Cheer": ("#c89f2a", "#000000", "★"),
    "ToggleOvercharge": ("#7a4a8a", "#ffffff", "⚡"),
    "ToggleFormationMode": ("#5b6777", "#ffffff", "▦"),
    "SelectWeapon": ("#444444", "#ffffff", "⇅"),
    "SnipeVehicle": ("#b42828", "#ffffff", "◎"),
    "UseWeapon": ("#b42828", "#ffffff", "⚔"),
    "SelectClearMines": ("#a07020", "#ffffff", "○"),
    "AddWaypoint": ("#1f6fb2", "#ffffff", "•"),
    "DirectParticleCannon": ("#7a4a8a", "#ffffff", "✦"),
    "CancelUnit": ("#8a1f1f", "#ffffff", "✕"),
    "CancelUpgrade": ("#8a1f1f", "#ffffff", "✕"),
    "CancelBuild": ("#8a1f1f", "#ffffff", "✕"),
    "BeginUpgrade": ("#3a7d3a", "#ffffff", "▲"),
    "CreateUnit": ("#2e6da4", "#ffffff", "U"),
    "BuildObject": ("#a07020", "#ffffff", "B"),
    "PurchaseScience": ("#c89f2a", "#000000", "★"),
    "SpecialPower": ("#7a4a8a", "#ffffff", "✦"),
    "SpecialPowerAtLocation": ("#7a4a8a", "#ffffff", "✦"),
    "SpecialPowerAtObject": ("#7a4a8a", "#ffffff", "✦"),
}

# Group icons (one per digit). Generated programmatically below.
GROUP_BG_CREATE = "#2e6da4"
GROUP_BG_SELECT = "#5b8a3a"


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in ("seguisym.ttf", "seguiemj.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_icon(bg: str, fg: str, glyph: str, font_size: int = 18) -> Image.Image:
    img = Image.new("RGBA", (28, 28), bg)
    draw = ImageDraw.Draw(img)
    font = _font(font_size)
    try:
        bbox = draw.textbbox((0, 0), glyph, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x = (28 - w) / 2 - bbox[0]
        y = (28 - h) / 2 - bbox[1]
    except AttributeError:
        w, h = draw.textsize(glyph, font=font)
        x = (28 - w) / 2
        y = (28 - h) / 2
    draw.text((x, y), glyph, fill=fg, font=font)
    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, (bg, fg, glyph) in SPECS.items():
        _draw_icon(bg, fg, glyph).save(OUT_DIR / f"{name}.png", format="PNG")
    for i in range(10):
        _draw_icon(GROUP_BG_CREATE, "#ffffff", f"+{i}", font_size=14).save(
            OUT_DIR / f"CreateGroup{i}.png", format="PNG"
        )
        _draw_icon(GROUP_BG_SELECT, "#ffffff", str(i), font_size=18).save(
            OUT_DIR / f"SelectGroup{i}.png", format="PNG"
        )
    print(f"Wrote {len(SPECS) + 20} action icons to {OUT_DIR}")


if __name__ == "__main__":
    main()
