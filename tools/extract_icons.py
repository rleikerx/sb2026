#!/usr/bin/env python3
"""
Extract inventory/UI icons from the cache as named PNG files.

Every COBJECT can carry an `obj_icon` texture ID, and character runes also
carry a `rune_class_icon` crest. Both are ordinary texture records, so this
resolves them through the AssetManager and writes them out with readable
filenames instead of bare numeric IDs.

Examples:
    # every icon in the catalogue, grouped into per-category folders
    python tools/extract_icons.py --out export_icons

    # just the class/discipline runes, at 4x for a modern UI
    python tools/extract_icons.py --out export_icons --kind Creature --scale 4

    # specific assets, plus a contact sheet to eyeball the result
    python tools/extract_icons.py --ids 2500,2501,2502 --contact-sheet sheet.png
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image, ImageOps

from assets.asset_manager import AssetManager
from assets.asset_catalog import AssetCatalog, AssetKind

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def slugify(name: str) -> str:
    """Filesystem-safe version of an in-game name."""
    return _UNSAFE.sub("_", (name or "").strip()).strip("_") or "unnamed"


def resize(img: Image.Image, scale: int, resample: str) -> Image.Image:
    if scale <= 1:
        return img
    filt = Image.Resampling.NEAREST if resample == "nearest" else Image.Resampling.LANCZOS
    return img.resize((img.width * scale, img.height * scale), filt)


def contact_sheet(images: List[tuple], path: Path, columns: int = 16) -> None:
    """Tile extracted icons into a single sheet for quick visual review."""
    if not images:
        return
    cell = max(max(im.width, im.height) for _, im in images)
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGBA", (columns * cell, rows * cell), (30, 30, 30, 255))
    for i, (_, im) in enumerate(images):
        x = (i % columns) * cell + (cell - im.width) // 2
        y = (i // columns) * cell + (cell - im.height) // 2
        sheet.paste(im, (x, y), im if im.mode == "RGBA" else None)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    print(f"contact sheet|path={path}|icons={len(images)}|grid={columns}x{rows}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", default=str(REPO_ROOT / "arcane_dump"), help="path to arcane_dump/")
    ap.add_argument("--out", default=str(REPO_ROOT / "export_icons"), help="output directory")
    ap.add_argument("--kind", action="append", help="limit to a category (repeatable): "
                                                    + ", ".join(k.value for k in AssetKind))
    ap.add_argument("--ids", help="comma-separated asset IDs instead of a whole category")
    ap.add_argument("--scale", type=int, default=1, help="integer upscale factor (default 1)")
    ap.add_argument("--resample", choices=("nearest", "lanczos"), default="lanczos",
                    help="upscale filter; 'nearest' keeps hard pixel edges")
    ap.add_argument("--flat", action="store_true", help="write into one folder instead of per-category")
    ap.add_argument("--class-icons", action="store_true", help="also export rune class crests")
    ap.add_argument("--contact-sheet", help="write a tiled preview of everything exported")
    ap.add_argument("--manifest", default="icons.json", help="index filename written into --out")
    args = ap.parse_args()

    am = AssetManager(args.dump)
    catalog = AssetCatalog(am)
    out_root = Path(args.out)

    # Build the work list.
    if args.ids:
        wanted = [int(x) for x in args.ids.split(",") if x.strip()]
    else:
        kinds = catalog.list_kinds()
        if args.kind:
            requested = {k.lower() for k in args.kind}
            kinds = [k for k in kinds if k.value.lower() in requested]
            if not kinds:
                print(f"no matching category|given={args.kind}", file=sys.stderr)
                return 2
        wanted = [aid for k in kinds for aid in catalog.iter_asset_ids(k)]

    manifest: List[Dict] = []
    previews: List[tuple] = []
    written = skipped = failed = 0
    seen_paths: Dict[str, int] = {}

    for asset_id in wanted:
        cobj = am.load_cobject(asset_id)
        if cobj is None:
            failed += 1
            continue

        name = catalog._get_name(asset_id)
        kind = catalog._get_kind(asset_id)

        targets = [("icon", cobj.icon_id)]
        if args.class_icons and cobj.class_icon_id:
            targets.append(("class", cobj.class_icon_id))

        for role, texture_id in targets:
            if not texture_id:
                skipped += 1
                continue

            img = am.load_texture_image(texture_id)
            if img is None:
                failed += 1
                continue

            # Same orientation fix the viewport applies on upload.
            img = ImageOps.mirror(img.rotate(180))
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            img = resize(img, args.scale, args.resample)

            stem = f"{asset_id}_{slugify(name)}" + ("" if role == "icon" else "_class")
            folder = out_root if args.flat else out_root / kind.value
            # Two assets can share a name; keep both.
            path = folder / f"{stem}.png"
            if str(path) in seen_paths:
                seen_paths[str(path)] += 1
                path = folder / f"{stem}_{seen_paths[str(path)]}.png"
            else:
                seen_paths[str(path)] = 0

            path.parent.mkdir(parents=True, exist_ok=True)
            img.save(path)
            written += 1

            manifest.append({
                "asset_id": asset_id,
                "name": name,
                "kind": kind.value,
                "role": role,
                "texture_id": texture_id,
                "file": str(path.relative_to(out_root)).replace("\\", "/"),
                "width": img.width,
                "height": img.height,
            })
            if args.contact_sheet:
                previews.append((name, img if img.mode == "RGBA" else img.convert("RGBA")))

    out_root.mkdir(parents=True, exist_ok=True)
    manifest_path = out_root / args.manifest
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"icons|written={written}|no_icon={skipped}|failed={failed}|out={out_root}")
    print(f"manifest|path={manifest_path}")

    if args.contact_sheet:
        contact_sheet(previews, Path(args.contact_sheet))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
