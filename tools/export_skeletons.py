#!/usr/bin/env python3
"""
Export the skeletons in full, and the small config lookup tables beside them.

`motions/skeletons.json` already carries name, parent, offset and length — enough to draw a rig and
not enough to *bind to* one. Three fields it drops matter:

- **`bind_pose_matrix`** — the 16-float rest transform. `graph/` places a part by naming its joint;
  without the joint's own rest transform you cannot resolve that name into a position.
- **`flip`** — the mirrored-limb flag. Shadowbane ships one arm mesh and mirrors it for the other
  side, which is why `asset_catalog._bind_parts_to_skeleton` has a `_mirror_part`. A rig read
  without this draws two left arms.
- **`axis` / `direction` / `flags`** — the joint's own frame and its attachment bits.

Also writes the index->name tables from the decrypted config, which are tiny and otherwise
invisible: guild heraldry is a colour, a pattern and a symbol chosen by index, and those indices
mean nothing without these lists.

Usage:
    python tools/export_skeletons.py
    python tools/export_skeletons.py --config export_aegisfall/config
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arcane.ArcSkeleton import ArcSkeleton
from assets.cache_archive import CacheArchive


def find_cache(dump: Path, name: str) -> Path | None:
    for path in sorted(dump.rglob(name)):
        return path
    return None


def bone_row(bone) -> dict:
    row = {
        "name": bone.name or f"hash_{bone.name_hash}",
        "nameHash": bone.name_hash,
        "parent": bone.parent_index,
        "length": round(float(bone.length), 6),
        "flags": bone.flags,
        # Non-zero means "this limb is the mirror of its opposite" — the reason one arm mesh
        # serves both sides. Dropping it is how a rig ends up with two left arms.
        "flip": bone.flip,
        "direction": [round(float(v), 6) for v in bone.direction],
        "axis": [round(float(v), 6) for v in bone.axis],
        "bindPose": [round(float(v), 6) for v in bone.bind_pose_matrix],
    }
    # The bind pose's translation column is what a consumer usually wants; surfaced so nobody has
    # to know whether this matrix is row- or column-major to get a joint position out of it.
    matrix = bone.bind_pose_matrix
    row["bindTranslation"] = [round(float(v), 6) for v in (matrix[12], matrix[13], matrix[14])]
    return row


def quoted_list(text: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r'"([^"]*)"', text)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", default=str(REPO_ROOT / "arcane_dump"))
    ap.add_argument("--config", default=str(REPO_ROOT / "export_aegisfall" / "config"))
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "rig"))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()

    path = find_cache(Path(args.dump), "Skeleton.cache")
    if path is None:
        print("Skeleton.cache not found", file=sys.stderr)
        return 1

    archive = CacheArchive(path)
    skeletons: dict[str, dict] = {}
    failed = 0
    flipped = 0
    for record_id in archive.ids():
        # `ArcSkeleton` is the *container* — it owns the SKEL magic, the version and the bone
        # list. `ArcBoneRecord` is the per-bone class. Reading a bone count and then looping
        # `ArcSkeleton()` per bone treats the container as a bone and fails on every record.
        skeleton = ArcSkeleton()
        try:
            skeleton.load_binary(archive.stream(record_id))
            bones = [bone_row(b) for b in skeleton.bones]
        except Exception as error:
            failed += 1
            print(f"  skeleton {record_id} failed: {type(error).__name__}: {error}",
                  file=sys.stderr)
            continue
        if not bones:
            continue
        flipped += sum(1 for b in bones if b["flip"])
        skeletons[str(record_id)] = {
            "boneCount": len(bones),
            "version": skeleton.version,
            "flags": skeleton.flags,
            "motionTokens": list(skeleton.motion_tokens),
            "bones": bones,
        }

    (out / "skeletons.json").write_text(
        json.dumps({"generator": "tools/export_skeletons.py",
                    "note": "full bone records: bind pose, mirror flag, axis, flags",
                    "skeletons": skeletons}, indent=1), encoding="utf-8")

    total = sum(s["boneCount"] for s in skeletons.values())
    print(f"skeletons {len(skeletons)}  bones {total}  mirrored bones {flipped}  failed {failed}")
    for sid, s in list(skeletons.items())[:4]:
        names = [b["name"] for b in s["bones"]]
        print(f"  {sid}: {s['boneCount']} bones — {', '.join(names[:8])} …")

    # --- the small lookup tables ---------------------------------------------------------
    config = Path(args.config) / "Config"
    tables: dict[str, object] = {}
    for name, key in (("Lookup_Color.cfg", "colors"),
                      ("Lookup_Pattern.cfg", "patterns"),
                      ("Lookup_Symbol.cfg", "symbols")):
        source = config / name
        if source.exists():
            tables[key] = quoted_list(source.read_text(encoding="latin-1"))

    resources = []
    source = config / "ResourceInfo.cfg"
    if source.exists():
        text = source.read_text(encoding="latin-1")
        for block in re.findall(r"<BEGINRESOURCEDATA>(.*?)<ENDRESOURCEDATA>", text, re.S):
            row = {}
            for field, cast in (("RESOURCETYPE", str), ("TEMPLATEID", int), ("ICONID", int)):
                m = re.search(rf'{field}=\s*"?([^"\n]+?)"?\s*$', block, re.M)
                if m:
                    try:
                        row[field.lower()] = cast(m.group(1).strip())
                    except ValueError:
                        row[field.lower()] = m.group(1).strip()
            if row:
                resources.append(row)
    if resources:
        tables["resources"] = resources

    if tables:
        (out / "tables.json").write_text(
            json.dumps({"generator": "tools/export_skeletons.py",
                        "note": "index->name tables; heraldry picks a colour, pattern and symbol "
                                "by index, and resources name their icon",
                        **tables}, indent=1), encoding="utf-8")
        print("\nlookup tables: " + ", ".join(
            f"{k} {len(v)}" for k, v in tables.items() if isinstance(v, list)))

    print(f"\nrig|elapsed={time.time() - started:.1f}s|out={out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
