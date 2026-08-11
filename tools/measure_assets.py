#!/usr/bin/env python3
"""
Measure every assembled asset: world-space size, footprint, and complexity.

The point is scale reference. Knowing that a keep is 78 units across and 40
tall, and that a door is 7, is what lets new models be authored at gameplay-
compatible proportions instead of eyeballed against screenshots.

Emits:
    dimensions.json   one row per asset
    dimensions.csv    same, for spreadsheets
    summary.json      per-category percentiles for width / depth / height /
                      footprint / triangles

Sizes are in raw cache units. `summary.json` also reports the median human
height, which is the natural yardstick for converting to metres.

Usage:
    python tools/measure_assets.py --out export_aegisfall/reference
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from assets.asset_manager import AssetManager
from assets.asset_catalog import AssetCatalog

PERCENTILES = (5, 25, 50, 75, 95)


class Measurer:
    def __init__(self, am: AssetManager, catalog: AssetCatalog):
        self.am = am
        self.catalog = catalog
        # mesh_id -> (8 local AABB corners, vertex count, triangle count)
        self._mesh_cache: Dict[int, Optional[Tuple[np.ndarray, int, int]]] = {}

    def mesh_info(self, mesh_id: int):
        if mesh_id in self._mesh_cache:
            return self._mesh_cache[mesh_id]

        mesh = self.am.load_mesh(mesh_id)
        info = None
        if mesh is not None and getattr(mesh, "mesh_vertices", None):
            v = np.asarray(mesh.mesh_vertices, dtype=np.float64)
            lo, hi = v.min(axis=0), v.max(axis=0)
            corners = np.array([[x, y, z]
                                for x in (lo[0], hi[0])
                                for y in (lo[1], hi[1])
                                for z in (lo[2], hi[2])], dtype=np.float64)
            tris = len(getattr(mesh, "mesh_indices", []) or []) // 3
            info = (corners, len(v), tris)

        # Meshes are shared heavily between assets; the cache keeps this pass
        # linear in distinct meshes rather than in parts.
        self._mesh_cache[mesh_id] = info
        return info

    def object_scale(self, asset_id: int):
        """
        The multiplier from `obj_scale` and `rune_scale_factor`, or None when both are unit.

        Both are per-axis tuples on the COBJECT record and they compose, so a creature whose rune
        scales it 1.5x and whose object scale is 0.9 ends up at 1.35x. Neither was read by any
        export before this.
        """
        try:
            cobj = self.am.load_cobject(asset_id)
        except Exception:
            return None
        raw = getattr(cobj, "_raw", None)
        if not isinstance(raw, dict):
            return None
        scale = np.ones(3, dtype=np.float64)
        seen = False
        for key in ("obj_scale", "rune_scale_factor"):
            value = raw.get(key)
            if value is None:
                continue
            try:
                factor = np.asarray([float(v) for v in value], dtype=np.float64)
            except (TypeError, ValueError):
                continue
            if factor.shape == (3,) and np.isfinite(factor).all() and (factor > 0).all():
                scale = scale * factor
                seen = True
        return scale if seen and not np.allclose(scale, 1.0) else None

    def measure(self, asset_id: int) -> Optional[dict]:
        asset = self.catalog.assemble(asset_id)
        if asset is None or not asset.parts:
            return None

        lo = np.full(3, np.inf)
        hi = np.full(3, -np.inf)
        verts = tris = 0
        textures = set()

        for part in asset.parts:
            info = self.mesh_info(part.mesh_id)
            if info is None:
                continue
            corners, nv, nt = info
            # Transforming the local AABB corners bounds the part tightly
            # enough for scale reference and avoids touching every vertex.
            world = (np.asarray(part.transform, dtype=np.float64)
                     @ np.hstack([corners, np.ones((8, 1))]).T).T[:, :3]
            lo = np.minimum(lo, world.min(axis=0))
            hi = np.maximum(hi, world.max(axis=0))
            verts += nv
            tris += nt
            if part.texture_id is not None:
                textures.add(part.texture_id)

        if not np.isfinite(lo).all():
            return None

        # --- apply the scales the COBJECT record carries -----------------------------------
        #
        # **The bind-pose envelope is not the in-world size**, and every figure this tool wrote
        # before now was the unscaled mesh. Two fields change it:
        #
        #   obj_scale          a uniform multiplier; unit for all but 17 assets, all weapons
        #   rune_scale_factor  74 distinct values from 0.8 to 2.0 across all 2,380 creatures
        #
        # The second is how one body mesh serves a goblin and a giant. Leaving it out made every
        # creature the same height, which matters here more than anywhere else because the
        # median creature height is what the units-per-metre constant is derived *from*.
        scale = self.object_scale(asset_id)
        if scale is not None:
            lo = lo * scale
            hi = hi * scale

        size = hi - lo
        return {
            "asset_id": asset_id,
            "name": asset.name,
            "kind": asset.kind.value,
            "width": round(float(size[0]), 3),
            "height": round(float(size[1]), 3),
            "depth": round(float(size[2]), 3),
            "footprint": round(float(size[0] * size[2]), 2),
            "min": [round(float(x), 3) for x in lo],
            "max": [round(float(x), 3) for x in hi],
            "parts": len(asset.parts),
            "vertices": verts,
            "triangles": tris,
            "textures": len(textures),
            "skeleton_id": asset.skeleton_id,
        }


def percentiles(values: List[float]) -> dict:
    if not values:
        return {}
    arr = np.asarray(values, dtype=np.float64)
    return {f"p{p}": round(float(np.percentile(arr, p)), 2) for p in PERCENTILES}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", default=str(REPO_ROOT / "arcane_dump"))
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "reference"))
    args = ap.parse_args()

    am = AssetManager(args.dump)
    catalog = AssetCatalog(am)
    measurer = Measurer(am, catalog)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: List[dict] = []
    started = time.time()
    for kind in catalog.list_kinds():
        for asset_id in catalog.iter_asset_ids(kind):
            row = measurer.measure(asset_id)
            if row is not None:
                rows.append(row)
        print(f"  {kind.value:10s} measured={len(rows)} ({time.time() - started:.0f}s)")

    with (out_dir / "dimensions.json").open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    columns = ["asset_id", "name", "kind", "width", "height", "depth", "footprint",
               "parts", "vertices", "triangles", "textures", "skeleton_id"]
    with (out_dir / "dimensions.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    summary = {}
    for kind in sorted({r["kind"] for r in rows}):
        subset = [r for r in rows if r["kind"] == kind]
        summary[kind] = {
            "count": len(subset),
            "width": percentiles([r["width"] for r in subset]),
            "height": percentiles([r["height"] for r in subset]),
            "depth": percentiles([r["depth"] for r in subset]),
            "footprint": percentiles([r["footprint"] for r in subset]),
            "triangles": percentiles([float(r["triangles"]) for r in subset]),
            "parts": percentiles([float(r["parts"]) for r in subset]),
        }

    # ------------------------------------------------------------------------------------
    # The metre yardstick, and it must be a *person*.
    #
    # This used to take the median height of all 2,380 creatures. That worked only because the
    # sizes were unscaled and therefore all much of a muchness. Now that `rune_scale_factor` is
    # applied the same statistic reads 7.632 units — the median of a bestiary containing giants
    # and dragons, which is not a yardstick for 1.8 m and would put the world at 4.24 units/m.
    #
    # Measured against the playable races instead: Human 4.934, Dwarf 4.055, Aracoix 8.685 (winged
    # and tall), median 5.437. Human is the one 1.8 m actually describes, so it leads; the median
    # and the bestiary figure are both reported so the choice is visible rather than buried.
    # ------------------------------------------------------------------------------------
    # **Lowest asset id wins.** The source ships most races twice — `2011_Human` and `2012_Human`,
    # a male body and a female one — so a plain name->row dict keeps whichever came last and
    # measured the Human at 4.192 units instead of 4.934. Aegisfall's own `stage-bodies.ts` made
    # this same choice for the same reason; matching it keeps the two repos on one yardstick.
    by_name: dict = {}
    for r in rows:
        if r["kind"] != "Creature":
            continue
        seen = by_name.get(r["name"])
        if seen is None or r["asset_id"] < seen["asset_id"]:
            by_name[r["name"]] = r
    playable = [
        "Aelfborn", "Aracoix", "Centaur", "Dwarf", "Elf", "Half-Giant",
        "Human", "Irekei", "Shade", "Minotaur", "Nephilim", "Vampire",
    ]
    races = [by_name[n] for n in playable if n in by_name]
    creatures = [r for r in rows if r["kind"] == "Creature" and r["skeleton_id"]]
    if races:
        human = by_name.get("Human")
        race_median = float(np.median([r["height"] for r in races]))
        summary["_scale_reference"] = {
            "units_per_metre": round((human["height"] if human else race_median) / 1.8, 4),
            "basis": "Human" if human else "median of the playable races",
            "human_height_units": round(human["height"], 3) if human else None,
            "playable_race_median_units": round(race_median, 3),
            "playable_races_measured": len(races),
            "per_race_units": {r["name"]: round(r["height"], 3) for r in races},
            "all_creature_median_units": round(
                float(np.median([r["height"] for r in creatures])), 3) if creatures else None,
            "note": "Heights are bind-pose and now include obj_scale and rune_scale_factor. "
                    "Divide a size by units_per_metre for an approximate metre value. The "
                    "all-creature median is reported for context only — it spans giants and "
                    "dragons and is not a human yardstick.",
        }

    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\nmeasured={len(rows)}|elapsed={time.time() - started:.1f}s|out={out_dir}")
    for kind, s in summary.items():
        if kind.startswith("_"):
            continue
        print(f"  {kind:10s} n={s['count']:5d}  "
              f"w(med)={s['width']['p50']:8.1f}  h(med)={s['height']['p50']:7.1f}  "
              f"d(med)={s['depth']['p50']:8.1f}  tris(med)={s['triangles']['p50']:8.0f}")
    if "_scale_reference" in summary:
        sr = summary["_scale_reference"]
        print(f"\nscale: {sr['basis']} = {sr['human_height_units']} units at 1.8 m "
              f"-> {sr['units_per_metre']} units/m")
        print(f"  playable-race median {sr['playable_race_median_units']} units;  "
              f"all-creature median {sr['all_creature_median_units']} "
              f"(bestiary — not a human yardstick)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
