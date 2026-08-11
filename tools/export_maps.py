#!/usr/bin/env python3
"""
Export the client's world maps: the three continent images and their marker icons.

These live **outside the caches**, in the install's `Maps/` folder, which is why nothing in this
repo had read them: every other tool here opens a `*.cache`. They are plain uncompressed TGA and a
`.wpak` that is an ordinary ZIP, so this is a format conversion rather than a decode.

Per world (`Aerynth`, `Dalgoth`, `Vorringia`) there are four pieces:

    <World>.TGA              1024x512 24-bit — the map as the player sees it
    <World>Territories.tga   1024x512 32-bit — per-territory colour key, alpha carries the mask
    <World>Highlight.tga     8-bit greyscale — the hover/selection overlay
    <World>Icons.wpak        49 32x32 TGAs — `B_*` terrain badges, `T_*` faction markers

`CZone.cache` gives every zone's contents but no parent link, so it cannot say where a zone sits on
a continent (`export_zones.py` documents that at length). **These images are the other half of that
question** — the shapes those zones were placed on, at a fixed 1024x512 per world.

Usage:
    python tools/export_maps.py
    python tools/export_maps.py --client "C:/Code/Shadowbane - Throne of Oblivion"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image

DEFAULT_CLIENT = r"C:\Code\Shadowbane - Throne of Oblivion"
WORLDS = ("Aerynth", "Dalgoth", "Vorringia")
# The suffixes each world ships, and what each one is for.
LAYERS = (
    ("", "map", "the map as the player sees it"),
    ("Territories", "territories", "per-territory colour key; alpha carries the mask"),
    ("Highlight", "highlight", "hover/selection overlay, 8-bit"),
)


def find(maps_dir: Path, world: str, suffix: str) -> Path | None:
    """`Aerynth.TGA` and `AerynthHighlight.tga` differ in case, so match case-insensitively."""
    want = f"{world}{suffix}.tga".lower()
    for path in maps_dir.iterdir():
        if path.name.lower() == want:
            return path
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--client", default=DEFAULT_CLIENT, help="the Shadowbane install directory")
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "maps"))
    args = ap.parse_args()

    maps_dir = Path(args.client) / "Maps"
    if not maps_dir.is_dir():
        print(f"no Maps/ under {args.client} — pass --client", file=sys.stderr)
        return 1

    out = Path(args.out)
    (out / "icons").mkdir(parents=True, exist_ok=True)
    started = time.time()

    index: list[dict] = []
    written = 0
    missing: list[str] = []
    icons_written = 0

    for world in WORLDS:
        entry: dict = {"world": world, "layers": {}, "icons": []}
        for suffix, key, note in LAYERS:
            path = find(maps_dir, world, suffix)
            if path is None:
                missing.append(f"{world}{suffix}.tga")
                continue
            image = Image.open(path)
            # 8-bit highlight layers stay greyscale; the rest carry colour and sometimes alpha.
            image = image.convert("L" if image.mode == "P" and suffix == "Highlight" else "RGBA")
            name = f"{world}_{key}.png"
            image.save(out / name)
            written += 1
            entry["layers"][key] = {
                "file": name, "w": image.width, "h": image.height, "note": note,
            }

        pack = maps_dir / f"{world}Icons.wpak"
        if pack.exists():
            # `.wpak` is an ordinary ZIP. Config.wpak's *entries* are encrypted; these are not,
            # which is worth stating because the extension alone does not tell you which you have.
            with zipfile.ZipFile(pack) as z:
                for name in sorted(z.namelist()):
                    if not name.lower().endswith(".tga"):
                        continue
                    target = out / "icons" / f"{name[:-4]}.png"
                    if not target.exists():
                        with z.open(name) as handle:
                            Image.open(handle).convert("RGBA").save(target)
                        icons_written += 1
                    entry["icons"].append(target.name)
        else:
            missing.append(f"{world}Icons.wpak")

        index.append(entry)

    (out / "index.json").write_text(
        json.dumps({"generator": "tools/export_maps.py",
                    "note": "client Maps/ folder: continent images, territory keys and markers",
                    "worlds": index}, indent=1), encoding="utf-8")

    # Present, not newly written. A second run writes nothing and would otherwise report
    # "one shared set of 0", which reads as a failure rather than as a no-op.
    icons_present = len(list((out / "icons").glob("*.png")))
    print(f"worlds {len(index)}  layers written {written}  "
          f"marker icons {icons_present} ({icons_written} new this run)")
    for row in index:
        got = ", ".join(f"{k} {v['w']}x{v['h']}" for k, v in row["layers"].items())
        print(f"  {row['world']:<12} {got}   icons {len(row['icons'])}")
    # The icon packs are identical across worlds, so the shared set is written once and each
    # world's index names it. Said out loud rather than leaving three counts that do not add up.
    print(f"marker icons are one shared set of {icons_present}, referenced by all three worlds")
    if missing:
        print(f"MISSING: {', '.join(missing)}")
    print(f"\nmaps|elapsed={time.time() - started:.1f}s|out={out}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
