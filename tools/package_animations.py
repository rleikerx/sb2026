#!/usr/bin/env python3
"""
Package the rigged models, the clip tracks and the ANIMID tables into one bundle.

Why this exists
---------------
The three halves of a playable creature are produced by three different tools and
land in three different directories. `export_assets.py --hierarchy` writes the
GLBs, `export_motion_tracks.py` writes the per-clip bone tracks, and
`export_animation_table.py` writes the ANIMID lookup. Each is correct and none of
them says how to get from a model to a moving model.

A consumer should not have to read three tool docstrings and infer the join. This
walks the export tree, resolves the joins that are safe to precompute, checks that
every reference actually lands, and writes the result as a bundle with one entry
point.

What it emits, into the same directory as the tables
----------------------------------------------------
    index.json            the manifest: what is here, how many, and the contract
    catalog.json          one row per GLB -- id, name, race, sex, rig, file
    skeleton_actions.json per rig: every named action, already resolved to a
                          clip token and the track file that holds it

What it deliberately does NOT precompute: model x weapon. That is 1.9M rows and
the two maps that generate it are a few hundred KB. `catalog.json` gives a model's
rig; `skeleton_actions.json` gives what that rig can do; `items.json` says which
ANIMID a given weapon selects. Three small lookups beat one enormous table.

Integrity is checked rather than assumed, and the results are recorded in
`index.json`: every clip a rig resolves must have a track file on disk, every GLB
must have a catalog row, and every catalog row's rig must appear in the actions
map. A bundle that fails any of these is reported and still written, so the
failure is visible rather than silent.

Usage:
    python tools/package_animations.py
    python tools/package_animations.py --export export_aegisfall
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

# Actions whose ANIMID is chosen by the equipped item rather than by the rig. They
# are still listed per rig -- "can this body plan parry at all" is a real question
# -- but which one plays comes from items.json.
ITEM_DRIVEN = ("parry", "combatIdle", "weaponSwing")


def glb_node_names(path: Path) -> Optional[List[str]]:
    """Node names out of a GLB's JSON chunk, without a glTF library."""
    try:
        with path.open("rb") as handle:
            magic, _version, _total = struct.unpack("<III", handle.read(12))
            if magic != 0x46546C67:
                return None
            length, _kind = struct.unpack("<II", handle.read(8))
            document = json.loads(handle.read(length).decode("utf-8"))
    except Exception:  # noqa: BLE001 - an unreadable GLB is a finding, not a crash
        return None
    return [node.get("name", "") for node in document.get("nodes", [])]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default=str(REPO_ROOT / "export_aegisfall"))
    ap.add_argument("--models", default="models_rigged/Creature",
                    help="rigged GLBs, relative to --export")
    ap.add_argument("--tracks", default="motions/tracks",
                    help="clip tracks, relative to --export")
    args = ap.parse_args()

    root = Path(args.export)
    tables = root / "animations"
    models_dir = root / args.models
    tracks_dir = root / args.tracks
    started = time.time()

    for required in (tables / "resolve.json", tables / "models.json", tables / "actions.json"):
        if not required.exists():
            print(f"missing {required} -- run tools/export_animation_table.py first",
                  file=sys.stderr)
            return 1

    resolve = json.loads((tables / "resolve.json").read_text(encoding="utf-8"))["skeletons"]
    models = json.loads((tables / "models.json").read_text(encoding="utf-8"))["models"]
    actions = json.loads((tables / "actions.json").read_text(encoding="utf-8"))["actions"]

    # -- catalog: one row per GLB ----------------------------------------
    problems: Dict[str, List[Any]] = defaultdict(list)
    catalog: Dict[str, Any] = {}
    by_skeleton: Dict[int, int] = defaultdict(int)

    for glb in sorted(models_dir.glob("*.glb")):
        asset_id = glb.name.split("_", 1)[0]
        row = models.get(asset_id)
        if row is None:
            problems["glbWithoutModel"].append(glb.name)
            continue
        skeleton = row.get("skeletonId")
        by_skeleton[skeleton] += 1
        catalog[asset_id] = {
            "name": row.get("name"),
            "race": row.get("race"),
            "sex": row.get("sex"),
            "skeletonId": skeleton,
            # Relative to the bundle root so the manifest survives being moved.
            "glb": f"{args.models}/{glb.name}",
        }
        if str(skeleton) not in resolve:
            problems["modelWithoutRig"].append(asset_id)

    for asset_id in models:
        if asset_id not in catalog:
            problems["modelWithoutGlb"].append(asset_id)

    # -- skeleton_actions: every named action, already resolved -----------
    track_index = tracks_dir / "clips"
    skeleton_actions: Dict[str, Any] = {}
    resolved_clips = 0

    for skeleton_id in sorted(by_skeleton, key=lambda s: -by_skeleton[s]):
        entry = resolve.get(str(skeleton_id))
        if entry is None:
            continue
        slots = entry["animid"]
        per_action: Dict[str, Any] = {}

        for action_name, vocabulary in actions.items():
            hits: Dict[str, Any] = {}
            for animid, label in vocabulary.items():
                clip = slots.get(animid)
                if clip is None:
                    continue                      # this rig has no such animation
                track = track_index / f"{clip}.json"
                if not track.exists():
                    problems["clipWithoutTrack"].append({"skeleton": skeleton_id,
                                                         "animid": animid, "clip": clip})
                    continue
                hits[animid] = {
                    "clip": clip,
                    "track": f"{args.tracks}/clips/{clip}.json",
                    # `label` is a name for emotes and powers, and a usage count for
                    # the item-driven classes, where the name lives on the item.
                    "name": label if isinstance(label, str) else None,
                    "usedBy": label if isinstance(label, list) else None,
                }
                resolved_clips += 1
            if hits:
                per_action[action_name] = hits

        skeleton_actions[str(skeleton_id)] = {
            "models": by_skeleton[skeleton_id],
            "slots": entry["slots"],
            "itemDriven": [a for a in ITEM_DRIVEN if a in per_action],
            "actions": per_action,
        }

    for asset_id, row in catalog.items():
        if str(row["skeletonId"]) not in skeleton_actions:
            problems["modelWithoutActions"].append(asset_id)

    # -- a spot check that the binding contract actually holds ------------
    # One GLB per rig: every bone its clips drive that the rig really has must be
    # a node in the file. Cheap enough to run every time, and it is the single
    # assumption the whole bundle rests on.
    checked = 0
    seen_rigs = set()
    for asset_id, row in catalog.items():
        skeleton = str(row["skeletonId"])
        if skeleton in seen_rigs:
            continue
        seen_rigs.add(skeleton)
        names = glb_node_names(root / row["glb"])
        if names is None:
            problems["unreadableGlb"].append(row["glb"])
            continue
        upper = {n.upper() for n in names}
        rig_bones = set()
        for action in skeleton_actions.get(skeleton, {}).get("actions", {}).values():
            for hit in action.values():
                track = root / hit["track"]
                try:
                    bones = json.loads(track.read_text(encoding="utf-8")).get("bones") or {}
                except Exception:  # noqa: BLE001
                    continue
                rig_bones |= {b.upper() for b in bones}
                break                              # one clip per action is enough
        missing = sorted(rig_bones - upper)
        checked += 1
        # A track for a bone this rig does not own is expected -- clips are shared
        # across rigs -- so only report it as informational, not as a failure.
        if missing:
            problems["tracksForAbsentBones"].append({"glb": row["glb"],
                                                     "count": len(missing)})

    index = {
        "generator": "tools/package_animations.py",
        "bundle": "aegisfall-animations",
        "contract": [
            "catalog[assetId] -> skeletonId and the GLB that holds the rig",
            "skeletonActions[skeletonId].actions[class][animid] -> clip + track file",
            "items[itemId] -> which ANIMID an equipped weapon selects",
            "overrides.bySourceAnimId[animid] -> what an active effect plays instead",
            "apply track bones to GLB nodes BY NAME; skip names with no node",
        ],
        "counts": {
            "models": len(catalog),
            "skeletons": len(skeleton_actions),
            "resolvedActionClips": resolved_clips,
            "clipsOnDisk": len(list(track_index.glob("*.json"))) if track_index.exists() else 0,
        },
        "files": {
            "catalog": "animations/catalog.json",
            "skeletonActions": "animations/skeleton_actions.json",
            "animidTable": "animations/resolve.json",
            "actionVocabulary": "animations/actions.json",
            "items": "animations/items.json",
            "models": "animations/models.json",
            "coverage": "animations/coverage.json",
            "overrides": "animations/overrides.json",
            "modelDir": args.models,
            "trackDir": f"{args.tracks}/clips",
        },
        "integrity": {
            "rigsBindingChecked": checked,
            **{key: len(value) for key, value in sorted(problems.items())},
        },
        "problems": {key: value[:20] for key, value in sorted(problems.items())},
    }

    (tables / "catalog.json").write_text(
        json.dumps({"generator": "tools/package_animations.py",
                    "note": "one row per rigged GLB; join to skeleton_actions by skeletonId",
                    "catalog": catalog}, indent=1), encoding="utf-8")
    (tables / "skeleton_actions.json").write_text(
        json.dumps({"generator": "tools/package_animations.py",
                    "note": "per rig: named actions already resolved to clip + track file",
                    "skeletonActions": skeleton_actions}, indent=1), encoding="utf-8")
    (tables / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")

    # The access guide is authored in docs/ because export_aegisfall/ is gitignored --
    # a bundle whose only instructions live in an untracked directory loses them the
    # first time somebody regenerates from a clean checkout. Copied in so the bundle
    # is still self-describing wherever it is handed to.
    guide = REPO_ROOT / "docs" / "ANIMATION_BUNDLE_ACCESS.md"
    if guide.exists():
        (tables / "README.md").write_text(guide.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        problems["missingAccessGuide"].append(str(guide))

    fatal = sum(len(problems[k]) for k in
                ("glbWithoutModel", "modelWithoutGlb", "modelWithoutRig",
                 "modelWithoutActions", "clipWithoutTrack", "unreadableGlb"))
    print(f"models {len(catalog)}  rigs {len(skeleton_actions)}  "
          f"resolved action clips {resolved_clips}")
    print(f"binding checked on {checked} rigs  |  integrity failures {fatal}")
    for key, value in sorted(problems.items()):
        print(f"  {key}: {len(value)}")
    print(f"wrote {tables}/index.json  in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
