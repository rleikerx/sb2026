#!/usr/bin/env python3
"""
Upscale cache textures to PNG for a modern-resolution release.

The client ships 32x32-512x512 art. This resamples every texture by an integer
factor and writes PNGs named by texture ID, so the result can feed
`tools/export_assets.py --texture-scale` or be dropped into an engine directly.

Filters:
    lanczos  smooth, best for photographic/organic art (default)
    nearest  hard pixel edges, best for UI art you want to stay crisp
    hybrid   lanczos, then an unsharp pass to recover edge definition

A neural upscaler (ESRGAN/waifu2x) would do better on the small textures, but
needs a model and a GPU pass; this stays dependency-free and deterministic.

Examples:
    python tools/upscale_textures.py --sample 12 --scale 4 --contact-sheet sheet.png
    python tools/upscale_textures.py --all --scale 2 --out export_textures
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image, ImageFilter, ImageOps

from assets.asset_manager import AssetManager

FILTERS = {
    "lanczos": Image.Resampling.LANCZOS,
    "nearest": Image.Resampling.NEAREST,
    "hybrid": Image.Resampling.LANCZOS,
}


def upscale(img: Image.Image, scale: int, mode: str) -> Image.Image:
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), FILTERS[mode])
    if mode == "hybrid":
        img = img.filter(ImageFilter.UnsharpMask(radius=max(1, scale), percent=90, threshold=3))
    return img


def contact_sheet(images: List[Image.Image], path: Path, columns: int = 6) -> None:
    if not images:
        return
    cell = max(max(im.width, im.height) for im in images)
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGBA", (columns * cell, rows * cell), (30, 30, 30, 255))
    for i, im in enumerate(images):
        x = (i % columns) * cell + (cell - im.width) // 2
        y = (i // columns) * cell + (cell - im.height) // 2
        sheet.paste(im.convert("RGBA"), (x, y))
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    print(f"contact sheet|path={path}|tiles={len(images)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", default=str(REPO_ROOT / "arcane_dump"))
    ap.add_argument("--out", default=str(REPO_ROOT / "export_textures"))
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--filter", choices=tuple(FILTERS), default="lanczos")
    ap.add_argument("--ids", help="comma-separated texture IDs")
    ap.add_argument("--sample", type=int, help="only the first N textures (test run)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--contact-sheet", help="before/after preview of the sampled textures")
    ap.add_argument("--manifest", default="textures.json")
    args = ap.parse_args()

    if not (args.ids or args.sample or args.all):
        ap.error("choose a selection: --ids, --sample N, or --all")

    am = AssetManager(args.dump)
    ids = ([int(x) for x in args.ids.split(",") if x.strip()] if args.ids
           else am.list_assets("texture"))
    if args.sample:
        ids = ids[: args.sample]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    records = []
    previews: List[Image.Image] = []
    failed = 0
    started = time.time()

    for n, tid in enumerate(ids, 1):
        img = am.load_texture_image(tid)
        if img is None:
            failed += 1
            continue

        # Same orientation fix the viewport applies on upload.
        img = ImageOps.mirror(img.rotate(180))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        src_w, src_h = img.width, img.height

        big = upscale(img, args.scale, args.filter)
        path = out_dir / f"{tid}.png"
        big.save(path)

        records.append({
            "texture_id": tid,
            "file": path.name,
            "source": [src_w, src_h],
            "output": [big.width, big.height],
            "mode": big.mode,
        })
        if args.contact_sheet and len(previews) < 24:
            previews.append(big)
        if n % 500 == 0:
            print(f"  ... {n}/{len(ids)} ({time.time() - started:.0f}s)")

    manifest_path = out_dir / args.manifest
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    total = sum((out_dir / r["file"]).stat().st_size for r in records)
    print(f"textures|written={len(records)}|failed={failed}|scale={args.scale}x"
          f"|filter={args.filter}|elapsed={time.time() - started:.1f}s|size={total / 1024 / 1024:.1f}MB")
    print(f"manifest|path={manifest_path}")
    for r in records[:8]:
        print(f"  {r['texture_id']:>8}  {r['source'][0]}x{r['source'][1]} -> "
              f"{r['output'][0]}x{r['output'][1]}  {r['mode']}")

    if args.contact_sheet:
        contact_sheet(previews, Path(args.contact_sheet))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
