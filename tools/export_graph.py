#!/usr/bin/env python3
"""
Export the assembly graph: how every asset is built from meshes, textures and joints.

`models/` gives finished GLBs and `models/assets.json` gives counts — 24 parts, 12 textures — which
is enough to browse and not enough to *rebuild*. This writes the graph those numbers summarise:
for each asset, every part with the mesh it draws, the texture on it, the joint it hangs from and
the transform that places it; plus a mesh table with vertex/triangle counts and local bounds, and a
texture table with pixel dimensions.

That is the answer to "how do I assemble and size this": a part list says what attaches where, the
mesh bounds say how big each piece is in source units, and the texture dimensions say what the UVs
were authored against. `reference/dimensions.json` already gives the whole-asset envelope and the
2.903 units/metre scale; this is the same question one level down.

Three files:

    graph/assets/<id>_<name>.json   parts: mesh, texture, joint, transform
    graph/meshes.json               per mesh: verts, tris, bounds, UV channels
    graph/textures.json             per texture: width, height, alpha

Usage:
    python tools/export_graph.py --sample 25
    python tools/export_graph.py --all
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from assets.asset_catalog import AssetCatalog, AssetKind
from assets.asset_manager import AssetManager

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def slug(name: str) -> str:
    return _UNSAFE.sub("_", (name or "").strip()).strip("_") or "unnamed"


def mesh_facts(mesh) -> dict:
    """Vertex and triangle counts plus the local bounding box, in source units."""
    verts = np.asarray(mesh.mesh_vertices, dtype=np.float64)
    out = {
        "verts": int(len(verts)),
        "tris": int(len(mesh.mesh_indices) // 3),
        # Per-vertex UVs, not channels: this list is the same length as the vertex list, and
        # calling it "uvChannels" read as "49 texture channels" rather than "49 UV pairs".
        "uvs": int(len(mesh.mesh_uv)) if isinstance(mesh.mesh_uv, list) else 0,
    }
    if len(verts):
        lo = verts.min(axis=0)
        hi = verts.max(axis=0)
        out["min"] = [round(float(v), 4) for v in lo]
        out["max"] = [round(float(v), 4) for v in hi]
        out["size"] = [round(float(v), 4) for v in (hi - lo)]
    return out


def sizing(manager, asset_id: int) -> dict:
    """
    The size and attachment fields the COBJECT record carries and no export had read.

    Three of them matter and none is in `reference/dimensions.json`, so every figure there is the
    *unscaled* mesh envelope:

    - `obj_scale` — a uniform multiplier. Unit for all but 17 assets, every one of them a weapon
      (great swords 0.9, a throwing hammer 2.0), so it is a small correction but a real one.
    - `rune_scale_factor` — **the one that matters**. 74 distinct values from 0.8 to 2.0 across the
      creature runes, which is how one body mesh serves a goblin and a giant. A creature's real
      height is its mesh envelope times this, and reading `dimensions.json` without it makes every
      creature the same size.
    - `obj_arc_hardpoint_list` — attachment sockets, `[type, id, [x,y,z, 4 rotation floats,
      sx,sy,sz]]`. The Tree of Life has 31. This is where a child object mounts.

    The four rotation floats are passed through unsplit: they are almost certainly a quaternion,
    but the component order is not confirmed and guessing it would be worse than saying so.
    """
    try:
        cobj = manager.load_cobject(asset_id)
    except Exception:
        return {}
    raw = getattr(cobj, "_raw", None)
    if not isinstance(raw, dict):
        return {}

    out: dict = {}
    scale = raw.get("obj_scale")
    if scale is not None:
        value = [round(float(v), 4) for v in scale]
        if value != [1.0, 1.0, 1.0]:
            out["objScale"] = value
    rune = raw.get("rune_scale_factor")
    if rune is not None:
        out["runeScaleFactor"] = [round(float(v), 4) for v in rune]
    forward = raw.get("obj_forward_vector")
    if forward is not None and any(forward):
        out["forwardVector"] = [round(float(v), 4) for v in forward]

    points = []
    for entry in raw.get("obj_arc_hardpoint_list") or []:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        transform = entry[2]
        if not isinstance(transform, (list, tuple)) or len(transform) < 10:
            continue
        points.append({
            "type": entry[0],
            "id": entry[1],
            "pos": [round(float(v), 4) for v in transform[0:3]],
            "rot": [round(float(v), 6) for v in transform[3:7]],
            "scale": [round(float(v), 4) for v in transform[7:10]],
        })
    if points:
        out["hardpoints"] = points
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", default=str(REPO_ROOT / "arcane_dump"))
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "graph"))
    ap.add_argument("--sample", type=int, help="N assets per category (test run)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--kind", action="append", help="limit to a category (repeatable)")
    args = ap.parse_args()

    out = Path(args.out)
    (out / "assets").mkdir(parents=True, exist_ok=True)

    manager = AssetManager(args.dump)
    catalog = AssetCatalog(manager)

    kinds = [AssetKind(k) for k in args.kind] if args.kind else list(catalog.list_kinds())
    started = time.time()

    mesh_table: dict[int, dict] = {}
    texture_table: dict[int, dict] = {}
    written = 0
    no_geometry = 0
    failed: list[str] = []
    parts_total = 0
    scaled = socketed = runescaled = 0
    joint_use: Counter = Counter()
    per_kind: Counter = Counter()

    for kind in kinds:
        ids = list(catalog.iter_asset_ids(kind))
        if args.sample:
            ids = ids[: args.sample]
        for asset_id in ids:
            try:
                asset = catalog.assemble(asset_id)
            except Exception as error:
                failed.append(f"{asset_id}: {type(error).__name__}: {error}")
                continue
            if asset is None or not asset.parts:
                no_geometry += 1
                continue

            parts = []
            for part in asset.parts:
                transform = np.asarray(part.transform, dtype=np.float64)
                # Translation is the useful column for placement; the basis is kept whole so a
                # part that is rotated or mirrored is not silently flattened to an offset.
                parts.append({
                    "meshId": part.mesh_id,
                    "textureId": part.texture_id,
                    "joint": part.target_bone,
                    "renderId": part.source_render_id,
                    "translation": [round(float(v), 4) for v in transform[:3, 3]],
                    "basis": [[round(float(v), 6) for v in row] for row in transform[:3, :3]],
                })
                joint_use[part.target_bone or "(none)"] += 1
                parts_total += 1

                if part.mesh_id not in mesh_table:
                    try:
                        mesh = manager.load_mesh(part.mesh_id)
                        if mesh is not None:
                            mesh_table[part.mesh_id] = mesh_facts(mesh)
                    except Exception:
                        pass
                if part.texture_id is not None and part.texture_id not in texture_table:
                    try:
                        texture = manager.load_texture(part.texture_id)
                        if texture is not None:
                            texture_table[part.texture_id] = {
                                "w": int(texture.image_width),
                                "h": int(texture.image_height),
                                "alpha": bool(texture.image_alpha),
                            }
                    except Exception:
                        pass

            record = {
                "assetId": asset.asset_id,
                "name": asset.name,
                "kind": str(asset.kind),
                "skeletonId": asset.skeleton_id,
                "renderIds": asset.render_ids,
                "parts": parts,
            }
            extra = sizing(manager, asset_id)
            record.update(extra)
            scaled += 'objScale' in extra
            socketed += 'hardpoints' in extra
            runescaled += 'runeScaleFactor' in extra
            (out / "assets" / f"{asset_id}_{slug(asset.name)}.json").write_text(
                json.dumps(record, separators=(",", ":")), encoding="utf-8")
            written += 1
            per_kind[str(asset.kind)] += 1

    (out / "meshes.json").write_text(
        json.dumps({"generator": "tools/export_graph.py",
                    "note": "per mesh: counts and local bounds in source units (2.903 = 1 m)",
                    "meshes": mesh_table}, indent=1), encoding="utf-8")
    (out / "textures.json").write_text(
        json.dumps({"generator": "tools/export_graph.py",
                    "note": "per texture: pixel dimensions the UVs were authored against",
                    "textures": texture_table}, indent=1), encoding="utf-8")

    print(f"assets written {written}  no geometry {no_geometry}  failed {len(failed)}")
    print(f"  with a non-unit objScale {scaled}  with hardpoints {socketed}  "
          f"with a runeScaleFactor {runescaled}")
    print(f"  by kind: {dict(per_kind)}")
    print(f"  parts {parts_total}, distinct meshes {len(mesh_table)}, "
          f"distinct textures {len(texture_table)}")
    print(f"  parts per asset: {parts_total / max(1, written):.1f}")
    named = sum(v for k, v in joint_use.items() if k != "(none)")
    print(f"  parts bound to a named joint: {named} of {parts_total}")
    print(f"  busiest joints: {dict(joint_use.most_common(8))}")
    if texture_table:
        sizes = Counter(f"{v['w']}x{v['h']}" for v in texture_table.values())
        print(f"  texture sizes: {dict(sizes.most_common(8))}")
    for line in failed[:8]:
        print(f"  FAILED {line}")
    print(f"\ngraph|elapsed={time.time() - started:.1f}s|out={out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
