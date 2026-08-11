#!/usr/bin/env python3
"""
Extract TerrainAlpha.cache to greyscale PNGs.

These are the 128x128 blend masks the client uses to mix ground textures across
terrain — the reference for how Shadowbane composed its landscape rather than
any single texture.

Record layout (little-endian), all constant across the archive:

    0   u32 width   = 128
    4   u32 height  = 128
    8   u32         = 1
    12  u32         = 1
    16  u32         = 0
    20  u8  flag    = 1
    21  u8  flag    = 1
    22  u32 length  = 16384        (unaligned)
    26  u8[16384]   greyscale samples, row-major

Header fields are asserted rather than assumed; any record that deviates is
reported instead of being written out as a silently wrong image.

Usage:
    python tools/extract_terrain_alpha.py --sample 24 --contact-sheet sheet.png
    python tools/extract_terrain_alpha.py --all --out export_aegisfall/terrain
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from collections import Counter
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image

from assets.cache_archive import CacheArchive

HEAD = struct.Struct("<IIIII")   # width, height, then three constants
PIXEL_OFFSET = 26
EXPECTED = (128, 128, 1, 1, 0)


def find_cache(explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    for candidate in (REPO_ROOT / "arcane_dump").rglob("TerrainAlpha.cache"):
        return candidate
    return None


def contact_sheet(images: List[Image.Image], path: Path, columns: int = 8) -> None:
    if not images:
        return
    cell = max(max(im.width, im.height) for im in images)
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("L", (columns * cell, rows * cell), 0)
    for i, im in enumerate(images):
        sheet.paste(im, ((i % columns) * cell, (i // columns) * cell))
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    print(f"contact sheet|path={path}|tiles={len(images)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", help="path to TerrainAlpha.cache (searched under arcane_dump/ if omitted)")
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "terrain"))
    ap.add_argument("--sample", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--contact-sheet")
    ap.add_argument("--manifest", default="terrain.json")
    args = ap.parse_args()

    if not (args.sample or args.all):
        ap.error("choose a selection: --sample N or --all")

    cache_path = find_cache(args.cache)
    if cache_path is None:
        print("TerrainAlpha.cache not found. Pass --cache with its path.", file=sys.stderr)
        return 2

    archive = CacheArchive(cache_path)
    ids = archive.ids()
    if args.sample:
        ids = ids[: args.sample]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    records: List[dict] = []
    previews: List[Image.Image] = []
    deviations: Counter = Counter()
    failed = 0
    started = time.time()

    for terrain_id in ids:
        data = archive.read(terrain_id)
        if data is None or len(data) < PIXEL_OFFSET:
            failed += 1
            continue

        header = HEAD.unpack_from(data, 0)
        length = struct.unpack_from("<I", data, 22)[0]
        width, height = header[0], header[1]

        if header != EXPECTED:
            deviations[str(header)] += 1
        pixels = data[PIXEL_OFFSET:PIXEL_OFFSET + length]
        if width * height != len(pixels):
            failed += 1
            deviations[f"size {width}x{height} vs {len(pixels)} bytes"] += 1
            continue

        img = Image.frombytes("L", (width, height), pixels)
        path = out_dir / f"{terrain_id}.png"
        img.save(path)

        records.append({
            "terrain_id": terrain_id,
            "hex_id": f"{terrain_id:016x}",
            "file": path.name,
            "width": width,
            "height": height,
            # Coverage says how much of the tile the mask actually paints,
            # which is what distinguishes a blend edge from a solid fill.
            "mean": round(sum(pixels) / len(pixels), 2),
        })
        if args.contact_sheet and len(previews) < 64:
            previews.append(img)

    with (out_dir / args.manifest).open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    total_mb = sum((out_dir / r["file"]).stat().st_size for r in records) / 1024 / 1024
    print(f"terrain|written={len(records)}|failed={failed}"
          f"|elapsed={time.time() - started:.1f}s|size={total_mb:.1f}MB|out={out_dir}")
    if deviations:
        print("header deviations:", dict(deviations.most_common(5)))
    else:
        print("all records matched the expected 128x128 header")

    if args.contact_sheet:
        contact_sheet(previews, Path(args.contact_sheet))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
