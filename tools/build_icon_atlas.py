#!/usr/bin/env python3
"""
Pack COBJECT icons into a sprite atlas for a modern client UI.

Produces `atlas_N.png` plus a JSON manifest giving each icon's asset ID, name,
category and pixel rect, which is what a web or engine UI needs to draw an
inventory grid from one texture instead of thousands of files.

Icons are bucketed by size and shelf-packed, so a page stays dense. Anything
that will not fit a page on its own is reported rather than silently dropped.

Examples:
    python tools/build_icon_atlas.py --sample 64 --scale 2 --out export_atlas
    python tools/build_icon_atlas.py --all --scale 2 --page 2048 --out export_atlas
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image, ImageOps

from assets.asset_manager import AssetManager
from assets.asset_catalog import AssetCatalog


class ShelfPacker:
    """Row-based packer: sort by height, fill shelves left to right."""

    def __init__(self, page: int, padding: int):
        self.page = page
        self.padding = padding
        self.x = padding
        self.y = padding
        self.shelf_height = 0

    def place(self, w: int, h: int) -> Optional[tuple]:
        if w + 2 * self.padding > self.page or h + 2 * self.padding > self.page:
            return None
        if self.x + w + self.padding > self.page:
            self.y += self.shelf_height + self.padding
            self.x = self.padding
            self.shelf_height = 0
        if self.y + h + self.padding > self.page:
            return "full"
        pos = (self.x, self.y)
        self.x += w + self.padding
        self.shelf_height = max(self.shelf_height, h)
        return pos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", default=str(REPO_ROOT / "arcane_dump"))
    ap.add_argument("--out", default=str(REPO_ROOT / "export_atlas"))
    ap.add_argument("--page", type=int, default=2048, help="atlas page size in px")
    ap.add_argument("--padding", type=int, default=2)
    ap.add_argument("--scale", type=int, default=1, help="integer upscale before packing")
    ap.add_argument("--resample", choices=("nearest", "lanczos"), default="lanczos")
    ap.add_argument("--kind", action="append", help="limit to a category (repeatable)")
    ap.add_argument("--sample", type=int, help="only N icons (test run)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--manifest", default="atlas.json")
    args = ap.parse_args()

    if not (args.sample or args.all or args.kind):
        ap.error("choose a selection: --sample N, --kind, or --all")

    am = AssetManager(args.dump)
    catalog = AssetCatalog(am)

    kinds = catalog.list_kinds()
    if args.kind:
        requested = {k.lower() for k in args.kind}
        kinds = [k for k in kinds if k.value.lower() in requested]
        if not kinds:
            print(f"no matching category|given={args.kind}", file=sys.stderr)
            return 2

    filt = (Image.Resampling.NEAREST if args.resample == "nearest"
            else Image.Resampling.LANCZOS)

    started = time.time()
    entries = []
    for kind in kinds:
        for asset_id in catalog.iter_asset_ids(kind):
            cobj = am.load_cobject(asset_id)
            if cobj is None or not cobj.icon_id:
                continue
            img = am.load_texture_image(cobj.icon_id)
            if img is None:
                continue
            img = ImageOps.mirror(img.rotate(180)).convert("RGBA")
            if args.scale > 1:
                img = img.resize((img.width * args.scale, img.height * args.scale), filt)
            entries.append({
                "asset_id": asset_id,
                "name": catalog._get_name(asset_id),
                "kind": kind.value,
                "texture_id": cobj.icon_id,
                "image": img,
            })
            if args.sample and len(entries) >= args.sample:
                break
        if args.sample and len(entries) >= args.sample:
            break

    # Tallest first keeps shelves tight.
    entries.sort(key=lambda e: (-e["image"].height, -e["image"].width))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    pages: List[Image.Image] = []
    records: List[Dict] = []
    oversized: List[int] = []
    packer = ShelfPacker(args.page, args.padding)
    page_img = Image.new("RGBA", (args.page, args.page), (0, 0, 0, 0))

    for entry in entries:
        img = entry["image"]
        spot = packer.place(img.width, img.height)
        if spot is None:
            oversized.append(entry["asset_id"])
            continue
        if spot == "full":
            pages.append(page_img)
            page_img = Image.new("RGBA", (args.page, args.page), (0, 0, 0, 0))
            packer = ShelfPacker(args.page, args.padding)
            spot = packer.place(img.width, img.height)
            if spot is None or spot == "full":
                oversized.append(entry["asset_id"])
                continue
        x, y = spot
        page_img.paste(img, (x, y))
        records.append({
            "asset_id": entry["asset_id"],
            "name": entry["name"],
            "kind": entry["kind"],
            "texture_id": entry["texture_id"],
            "page": len(pages),
            "x": x, "y": y, "w": img.width, "h": img.height,
        })
    pages.append(page_img)

    for i, page in enumerate(pages):
        page.save(out_dir / f"atlas_{i}.png")

    manifest = {
        "page_size": args.page,
        "padding": args.padding,
        "scale": args.scale,
        "pages": [f"atlas_{i}.png" for i in range(len(pages))],
        "icons": records,
    }
    manifest_path = out_dir / args.manifest
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    used = sum(r["w"] * r["h"] for r in records)
    capacity = len(pages) * args.page * args.page
    print(f"atlas|icons={len(records)}|pages={len(pages)}|page_size={args.page}"
          f"|fill={100.0 * used / capacity:.1f}%|elapsed={time.time() - started:.1f}s")
    if oversized:
        print(f"oversized (did not fit a page)|count={len(oversized)}|ids={oversized[:10]}")
    print(f"manifest|path={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
