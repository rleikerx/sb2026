#!/usr/bin/env python3
"""
Export Tile.cache and Visual.cache as JSON.

Neither is part of the model graph the viewer walks, but both are decodable
with parsers the repo already has and neither had ever been read:

    Tile.cache    9 records, each an ArcTileManager - the terrain tile sets
                  (patterns and masks) that pair with the TerrainAlpha blends
    Visual.cache  480 records, each an ArcVisual - particle, lightning and
                  geometry effects (spell FX, weather, torches)

Both are small, so this emits one JSON document per cache rather than a file
per record.

Usage:
    python tools/export_effects.py --out export_aegisfall/effects
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arcane.util import ResStream
from arcane.ArcTile import ArcTileManager
from arcane.ArcVisual import ArcVisual
from assets.cache_archive import CacheArchive


def find_cache(name: str, explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    for candidate in (REPO_ROOT / "arcane_dump").rglob(name):
        return candidate
    return None


def export(cache_path: Path, cls, out_path: Path) -> dict:
    archive = CacheArchive(cache_path)
    rows = []
    failed = 0
    partial = 0

    for record_id in archive.ids():
        raw = archive.read(record_id)
        if raw is None:
            failed += 1
            continue
        try:
            stream = ResStream(raw)
            obj = cls()
            obj.load_binary(stream)
            # A record the parser did not consume to the end means the layout
            # is only partly understood; flag it rather than trusting it.
            consumed = stream.buffer.tell() == len(raw)
            data = obj.save_json()
        except Exception as e:
            failed += 1
            print(f"  parse failed|id={record_id}|err={type(e).__name__}: {e}", file=sys.stderr)
            continue
        if not consumed:
            partial += 1
        rows.append({"id": record_id, "fully_parsed": consumed, "data": data})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, default=str)

    return {"records": len(rows), "failed": failed, "partial": partial,
            "bytes": out_path.stat().st_size, "path": out_path}


def effect_texture_ids(rows: list) -> "Counter":
    """
    Every texture an effect draws with, counted by how many effects use it.

    `visuals.json` describes *how* an effect moves but names its artwork only by ID, so on its own
    the bundle cannot be looked at — a particle system is a texture plus a curve, and one of those
    was missing. The fields are `particle_texture`, `geometry_texture`, `geometry_texture_proj` and
    `lightning_texture`; they are collected by name at any depth rather than by walking the effect
    schema, because the three effect types nest differently and a fourth would otherwise be missed
    in silence.
    """
    wanted = ("particle_texture", "geometry_texture", "geometry_texture_proj", "lightning_texture")
    found: Counter = Counter()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in wanted and isinstance(value, int) and value > 0:
                    found[value] += 1
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(rows)
    return found


def export_effect_textures(dump: str, ids: "Counter", out_dir: Path, scale: int,
                           resample: str) -> dict:
    """Write each effect texture as a PNG, named `<id>.png`, with an index beside them."""
    from PIL import Image, ImageOps

    from assets.asset_manager import AssetManager

    manager = AssetManager(dump)
    out_dir.mkdir(parents=True, exist_ok=True)
    written, missing, failed = 0, [], []
    index = []

    for texture_id, uses in sorted(ids.items(), key=lambda kv: -kv[1]):
        try:
            image = manager.load_texture_image(texture_id)
        except Exception as error:  # a texture that will not decode is named, not swallowed
            failed.append((texture_id, f"{type(error).__name__}: {error}"))
            continue
        if image is None:
            missing.append(texture_id)
            continue
        # The same vertical flip the viewer applies on upload, so these match what the
        # client draws rather than being mirrored (`export_assets.py` does the same).
        image = ImageOps.flip(image)
        if scale > 1:
            filt = Image.Resampling.NEAREST if resample == "nearest" else Image.Resampling.LANCZOS
            image = image.resize((image.width * scale, image.height * scale), filt)
        path = out_dir / f"{texture_id}.png"
        image.save(path)
        written += 1
        index.append({"texture_id": texture_id, "used_by_effects": uses,
                      "file": path.name, "w": image.width, "h": image.height})

    (out_dir / "index.json").write_text(
        json.dumps({"generator": "tools/export_effects.py --textures",
                    "note": "textures referenced by Visual.cache effects, most-used first",
                    "textures": index}, indent=1), encoding="utf-8")
    return {"written": written, "missing": missing, "failed": failed}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tile-cache")
    ap.add_argument("--visual-cache")
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "effects"))
    ap.add_argument("--textures", action="store_true",
                    help="also write the textures the effects draw with, as PNGs")
    ap.add_argument("--dump", default=str(REPO_ROOT / "arcane_dump"))
    ap.add_argument("--scale", type=int, default=1, help="integer upscale for effect textures")
    ap.add_argument("--resample", choices=("nearest", "lanczos"), default="lanczos")
    args = ap.parse_args()

    out_dir = Path(args.out)
    started = time.time()

    jobs = [
        ("Tile.cache", args.tile_cache, ArcTileManager, "tiles.json"),
        ("Visual.cache", args.visual_cache, ArcVisual, "visuals.json"),
    ]

    missing = []
    for cache_name, explicit, cls, filename in jobs:
        path = find_cache(cache_name, explicit)
        if path is None:
            missing.append(cache_name)
            continue
        result = export(path, cls, out_dir / filename)
        print(f"{filename:14s} records={result['records']:4d} failed={result['failed']} "
              f"partial={result['partial']} size={result['bytes'] / 1024:.0f}KB")

    if missing:
        print(f"not found|{','.join(missing)} — pass --tile-cache / --visual-cache",
              file=sys.stderr)

    # Effect types are the useful summary from Visual.cache.
    visuals_path = out_dir / "visuals.json"
    if visuals_path.exists():
        rows = json.loads(visuals_path.read_text(encoding="utf-8"))
        kinds = Counter()
        for row in rows:
            data = row.get("data") or {}
            for key, value in data.items():
                if isinstance(value, list) and value:
                    kinds[key] += len(value)
        if kinds:
            print("visual components:", dict(kinds.most_common(6)))

        texture_ids = effect_texture_ids(rows)
        print(f"effect textures referenced: {len(texture_ids)} distinct, "
              f"{sum(texture_ids.values())} references")
        if args.textures:
            result = export_effect_textures(args.dump, texture_ids,
                                            out_dir / "textures", args.scale, args.resample)
            print(f"textures       written={result['written']} "
                  f"absent_from_cache={len(result['missing'])} failed={len(result['failed'])}")
            # Named rather than counted: an ID the cache does not hold is a fact about this
            # build, and a silent difference between 133 wanted and 130 written is the kind of
            # gap that gets mistaken for a complete export later.
            if result["missing"]:
                print(f"  not in Textures.cache: "
                      f"{', '.join(str(i) for i in sorted(result['missing'])[:20])}")
            for texture_id, error in result["failed"][:10]:
                print(f"  FAILED {texture_id}: {error}")
            accounted = result["written"] + len(result["missing"]) + len(result["failed"])
            if accounted != len(texture_ids):
                print(f"MISMATCH: {len(texture_ids)} referenced but {accounted} accounted for")

    print(f"\neffects|elapsed={time.time() - started:.1f}s|out={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
