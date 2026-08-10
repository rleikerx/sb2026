#!/usr/bin/env python3
"""
Export assembled assets to glTF 2.0 / GLB for use in a modern engine.

Each asset becomes one file: every mesh part is a node carrying its own
transform, with the base texture embedded. Creature parts are placed on their
skeleton joints, so characters export upright rather than heaped at the origin.

The skeleton's own rest pose is a zero pose — limbs fully extended, feet
pointing at the floor — because in the client a character's stance comes from
the animation. Creatures are therefore posed standing by default, each on the
calmest standing frame its own skeleton has; `--pose` picks a clip by hand and
`--rest-pose` turns it off.

`--hierarchy` writes the rig instead of flattening it: every bone becomes a node
holding its own local transform, each part is parented to the joint it hangs
from, and bone name and mirror flag go in node `extras`. There are no skinning
weights and no `skins` array, because Shadowbane attaches one rigid mesh per
bone — a part is an ordinary child of its joint. The bone names are the source's
own, so the clips in `motions/tracks/` drive the file by name with nothing else
needed, and a consumer is no longer restricted to the body plans this exporter
happens to have a stance heuristic for.

Textures are written with the same vertical flip the viewer applies on upload,
which lines the raw UVs up with glTF's top-left origin, so no UV rewrite is
needed.

Examples:
    # sample run: five of each category, with a summary
    python tools/export_assets.py --sample 5 --out export_gltf

    # a specific set
    python tools/export_assets.py --ids 124100,24000,2000 --out export_gltf

    # a hand-picked stance instead of the automatic one
    python tools/export_assets.py --ids 2000 --pose 1000216 --out export_gltf

    # the raw rest pose, as the cache stores it
    python tools/export_assets.py --ids 2000 --rest-pose --out export_gltf

    # the rig itself, for a consumer that drives bones from the motion tracks
    python tools/export_assets.py --kind Creature --hierarchy --rest-pose \
        --out export_aegisfall/models_rigged

    # everything, textures upscaled 2x
    python tools/export_assets.py --all --texture-scale 2 --out export_gltf
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import trimesh
from PIL import Image, ImageOps

from assets.asset_manager import AssetManager
from assets.asset_catalog import REST_WITH_WINGS_FOLDED, AssetCatalog, AssetKind

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def slugify(name: str) -> str:
    return _UNSAFE.sub("_", (name or "").strip()).strip("_") or "unnamed"


def merge_manifest(path: Path, records: List[dict], attempted: Iterable[int]) -> List[dict]:
    """
    Fold this run's records into the manifest already at `path`.

    A partial export knows only about what it exported, so writing its records
    straight out drops every asset the run did not touch — point a `--kind`
    run at a manifest indexing all six categories and five of them vanish,
    leaving their files on disk with nothing pointing at them.

    The run is authoritative for the IDs it attempted and nothing else: those
    rows are replaced, or removed when the asset no longer yields geometry.
    Rows for assets outside the selection are carried through untouched.
    """
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return records          # no readable manifest yet, so this run is all of it
    if not isinstance(existing, list):
        return records

    fresh = {r["asset_id"]: r for r in records}
    touched = set(attempted)

    merged: List[dict] = []
    for row in existing:
        asset_id = row.get("asset_id")
        if asset_id in fresh:
            merged.append(fresh.pop(asset_id))
        elif asset_id not in touched:
            merged.append(row)
        # else: attempted this run and produced nothing, so it is gone now
    merged.extend(fresh.values())
    return merged


class AssetExporter:
    def __init__(self, asset_manager: AssetManager, catalog: AssetCatalog,
                 texture_scale: int = 1, resample: str = "lanczos",
                 pose: Optional[Dict[str, tuple]] = None, hierarchy: bool = False):
        self.am = asset_manager
        self.catalog = catalog
        self.texture_scale = max(1, texture_scale)
        self.resample = resample
        self.pose = pose
        self.hierarchy = hierarchy
        self._texture_cache: Dict[int, Optional[Image.Image]] = {}

    # ------------------------------------------------------------------
    def texture(self, texture_id: int) -> Optional[Image.Image]:
        if texture_id in self._texture_cache:
            return self._texture_cache[texture_id]

        img = self.am.load_texture_image(texture_id)
        if img is not None:
            # Match the viewport's orientation fix.
            img = ImageOps.mirror(img.rotate(180))
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            if self.texture_scale > 1:
                filt = (Image.Resampling.NEAREST if self.resample == "nearest"
                        else Image.Resampling.LANCZOS)
                img = img.resize(
                    (img.width * self.texture_scale, img.height * self.texture_scale), filt
                )
        self._texture_cache[texture_id] = img
        return img

    def build_geometry(self, part) -> Optional[trimesh.Trimesh]:
        mesh = self.am.load_mesh(part.mesh_id)
        if mesh is None or not getattr(mesh, "mesh_vertices", None):
            return None

        vertices = np.asarray(mesh.mesh_vertices, dtype=np.float64)
        indices = np.asarray(mesh.mesh_indices, dtype=np.int64)
        if indices.size < 3:
            return None
        faces = indices[: (indices.size // 3) * 3].reshape(-1, 3)
        # Drop faces that reference vertices the mesh does not have.
        faces = faces[(faces < len(vertices)).all(axis=1)]
        if not len(faces):
            return None

        geom = trimesh.Trimesh(vertices=vertices, faces=faces, process=False, validate=False)

        normals = getattr(mesh, "mesh_normals", None)
        if normals is not None and len(normals) == len(vertices):
            geom.vertex_normals = np.asarray(normals, dtype=np.float64)

        uvs = getattr(mesh, "mesh_uv", None)
        image = self.texture(part.texture_id) if part.texture_id is not None else None
        if uvs is not None and len(uvs) == len(vertices):
            geom.visual = trimesh.visual.TextureVisuals(
                uv=np.asarray(uvs, dtype=np.float64),
                image=image,
            )
        return geom

    @staticmethod
    def add_bones(scene: "trimesh.Scene", asset) -> None:
        """
        Write the rig into the scene graph as empty nodes, parents first.

        Every bone goes in, not just the ones carrying a mesh: the motion tracks
        address bones by name, so a rig missing its unskinned joints cannot be
        driven by them. Nothing here is a skin — Shadowbane attaches one rigid
        mesh per bone, so the parts are ordinary children of the joint they hang
        from and the file needs no weights at all.
        """
        for name, (parent, local, flip) in asset.bones.items():
            scene.graph.update(
                frame_to=name,
                frame_from=parent or scene.graph.base_frame,
                matrix=np.array(local, dtype=np.float64).reshape(4, 4),
                metadata={"bone": name, "flip": bool(flip)},
            )

    def export(self, asset_id: int, out_dir: Path, fmt: str) -> Optional[dict]:
        asset = self.catalog.assemble(asset_id, pose=self.pose)
        if asset is None or not asset.parts:
            return None

        scene = trimesh.Scene()
        rigged = self.hierarchy and bool(asset.bones)
        if rigged:
            self.add_bones(scene, asset)

        added = 0
        textures = set()
        for i, part in enumerate(asset.parts):
            geom = self.build_geometry(part)
            if geom is None:
                continue
            name = f"part{i:03d}_mesh{part.mesh_id}"
            if part.target_bone:
                name += f"_{slugify(part.target_bone)}"

            if rigged and part.target_bone in asset.bones and part.local_transform is not None:
                # Parent to the joint and hand over the render's own transform,
                # so replacing a bone rotation moves everything under it.
                parent = part.target_bone
                matrix = np.asarray(part.local_transform, dtype=np.float64)
            else:
                parent = scene.graph.base_frame
                matrix = np.asarray(part.transform, dtype=np.float64)

            scene.add_geometry(
                geom,
                geom_name=name,
                node_name=name,
                parent_node_name=parent,
                transform=matrix,
            )
            if rigged:
                scene.graph.update(
                    frame_to=name, frame_from=parent, matrix=matrix,
                    metadata={
                        "bone": part.target_bone,
                        "flip": bool(part.mirrored),
                        "meshId": int(part.mesh_id),
                    },
                )
            added += 1
            if part.texture_id is not None:
                textures.add(part.texture_id)

        if not added:
            return None

        folder = out_dir / asset.kind.value
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{asset_id}_{slugify(asset.name)}.{fmt}"
        scene.export(str(path))

        return {
            "asset_id": asset_id,
            "name": asset.name,
            "kind": asset.kind.value,
            "parts": added,
            "skipped_parts": len(asset.parts) - added,
            "textures": len(textures),
            "skeleton_id": asset.skeleton_id,
            "file": str(path.relative_to(out_dir)).replace("\\", "/"),
            "bytes": path.stat().st_size,
        }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", default=str(REPO_ROOT / "arcane_dump"))
    ap.add_argument("--out", default=str(REPO_ROOT / "export_gltf"))
    ap.add_argument("--format", choices=("glb", "gltf"), default="glb")
    ap.add_argument("--ids", help="comma-separated asset IDs")
    ap.add_argument("--kind", action="append", help="limit to a category (repeatable)")
    ap.add_argument("--sample", type=int, help="export N assets per category (test run)")
    ap.add_argument("--all", action="store_true", help="export every asset that has geometry")
    ap.add_argument("--texture-scale", type=int, default=1, help="integer texture upscale")
    ap.add_argument("--resample", choices=("nearest", "lanczos"), default="lanczos")
    ap.add_argument("--pose", help="stand the model on a specific clip frame: MOTION_ID[:FRAME]")
    ap.add_argument("--rest-pose", action="store_true",
                    help="export the cache's rest pose, skipping the automatic creature stand")
    ap.add_argument("--fold-wings", action="store_true",
                    help="with --rest-pose: keep the authored wing fold, so wings are not splayed. "
                         "For a consumer that re-poses the body itself but cannot unsplay a wing, "
                         "because no frame in this cache holds one folded (see WING_FOLD_SKELETONS)")
    ap.add_argument("--manifest", default="assets.json")
    ap.add_argument("--hierarchy", action="store_true",
                    help="write the bone tree into the file and parent each part to its "
                         "joint, instead of baking joints into part transforms")
    ap.add_argument("--fresh-manifest", action="store_true",
                    help="write only this run's rows, discarding any manifest already there")
    args = ap.parse_args()

    if not (args.ids or args.sample or args.all or args.kind):
        ap.error("choose a selection: --ids, --sample N, --kind, or --all")

    am = AssetManager(args.dump)
    catalog = AssetCatalog(am)

    if args.pose and args.rest_pose:
        ap.error("--pose and --rest-pose ask for opposite things")

    if args.fold_wings and not args.rest_pose:
        ap.error("--fold-wings is a modifier on --rest-pose; a standing creature already folds them")
    pose = (REST_WITH_WINGS_FOLDED if args.fold_wings else False) if args.rest_pose else None
    if args.pose:
        motion_id, _, frame = args.pose.partition(":")
        try:
            pose = am.load_motion_pose(int(motion_id), int(frame or 0))
        except ValueError:
            ap.error(f"--pose wants MOTION_ID[:FRAME], got {args.pose!r}")
        if not pose:
            # Most clips carry frames; the metadata-only ones would silently
            # export the zero pose, which is the thing --pose exists to avoid.
            ap.error(f"motion {motion_id} has no frame data to pose from")
        print(f"pose|motion={motion_id}|frame={frame or 0}|bones={len(pose)}")

    exporter = AssetExporter(am, catalog, args.texture_scale, args.resample, pose,
                             hierarchy=args.hierarchy)
    out_dir = Path(args.out)

    kinds = catalog.list_kinds()
    if args.kind:
        requested = {k.lower() for k in args.kind}
        kinds = [k for k in kinds if k.value.lower() in requested]
        if not kinds:
            print(f"no matching category|given={args.kind}", file=sys.stderr)
            return 2

    if args.ids:
        wanted = [int(x) for x in args.ids.split(",") if x.strip()]
    else:
        wanted = []
        for kind in kinds:
            ids = list(catalog.iter_asset_ids(kind))
            if args.sample:
                # Prefer assets that actually have geometry for a test run.
                picked = []
                for aid in ids:
                    a = catalog.assemble(aid)
                    if a and a.parts:
                        picked.append(aid)
                    if len(picked) >= args.sample:
                        break
                wanted.extend(picked)
            else:
                wanted.extend(ids)

    records: List[dict] = []
    failed: List[int] = []
    empty = 0
    started = time.time()

    for n, asset_id in enumerate(wanted, 1):
        try:
            rec = exporter.export(asset_id, out_dir, args.format)
        except Exception as e:
            failed.append(asset_id)
            print(f"export failed|id={asset_id}|err={type(e).__name__}: {e}", file=sys.stderr)
            continue
        if rec is None:
            empty += 1
            continue
        records.append(rec)
        if n % 250 == 0:
            print(f"  ... {n}/{len(wanted)} ({time.time() - started:.0f}s)")

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / args.manifest
    rows = records if args.fresh_manifest else merge_manifest(manifest_path, records, wanted)
    kept = len(rows) - len(records)
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    total_bytes = sum(r["bytes"] for r in records)
    print(f"\nexported={len(records)}|no_geometry={empty}|failed={len(failed)}"
          f"|elapsed={time.time() - started:.1f}s|size={total_bytes / 1024 / 1024:.1f}MB")
    print(f"manifest|path={manifest_path}|rows={len(rows)}|written={len(records)}|carried={kept}")
    for r in records[:12]:
        print(f"  {r['kind']:10s} {r['asset_id']:>9} {r['name'][:28]:30s} "
              f"parts={r['parts']:3d} tex={r['textures']:2d} {r['bytes'] / 1024:8.1f}KB  {r['file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
