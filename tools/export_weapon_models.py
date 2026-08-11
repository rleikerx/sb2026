"""Copy the weapon models plus a manifest into a client's public directory.

The content export already carries `asset_id` on every item, and the model files are named
`{asset_id}_{name}.glb`, so nothing has to be matched by name — the key is shared and exact. All 811
rows of `type: WEAPON` have a model on disk.

The manifest is the useful half. It carries the id, the name, the skill the game already uses to
classify the weapon, whether it is two-handed, and the measured bounding box — so a client can size
and orient a mesh without opening it, and can group 811 weapons into the handful of kinds its rig
knows about.

    python tools/export_weapon_models.py --out ../adventure-dev/packages/client/public/weapons

Sizes are reported rather than assumed: this is the step that decides whether a repository is
carrying 25 MB or 250.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil

EXPORT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "export_aegisfall")
ITEMS = os.path.join(EXPORT, "models", "Item")

# The measured asset scale factor (`D-100`, re-derived). Stated here so the manifest can carry
# metres, which is the only unit the simulation and the renderer both agree on.
#
# **Was 2.903, from the median height of all 2,380 creatures.** D-100 said outright that the
# creature measurement "is circular on its own", and it was also taken before anything read
# `rune_scale_factor` — the per-creature 0.8x-2.0x multiplier that is how one body mesh serves a
# goblin and a giant. Unscaled, every creature measured much the same height, which is what made a
# bestiary-wide median look like a character.
#
# Measured on the Human specifically, with that scale applied, the figure is 2.7411 — but this
# stays 2.903 to match `UNITS_PER_METRE` in @aegisfall/core, which cannot move without relocating
# every camp in the world and every persisted character position with it. A manifest carrying a
# different scale from the simulation reading it is worse than a slightly-off scale in both.
UNITS_PER_METRE = 2.903


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="directory to write the GLBs and manifest.json into")
    ap.add_argument("--skills", default="", help="comma-separated skills to include (default: all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    dims = {d["asset_id"]: d for d in json.load(open(f"{EXPORT}/reference/dimensions.json"))}
    rows = json.load(open(f"{EXPORT}/content/items.json"))

    on_disk: dict[int, str] = {}
    for fn in os.listdir(ITEMS):
        m = re.match(r"(\d+)_(.+)\.glb$", fn)
        if m:
            on_disk[int(m.group(1))] = fn

    wanted = {s.strip() for s in args.skills.split(",") if s.strip()}
    manifest = []
    total = 0
    missing = []

    for r in rows:
        if r.get("type") != "WEAPON":
            continue
        skill = r.get("skill_used")
        if wanted and str(skill) not in wanted:
            continue
        fn = on_disk.get(r["asset_id"])
        if fn is None:
            missing.append(r["name"])
            continue
        size = os.path.getsize(os.path.join(ITEMS, fn))
        total += size
        d = dims.get(r["asset_id"], {})
        # The longest axis is the weapon's own length whichever way the mesh was authored, which is
        # what a rig needs to scale it against a character rather than against a bounding cube.
        longest = max(d.get("width", 0.0), d.get("height", 0.0), d.get("depth", 0.0))
        manifest.append(
            {
                "id": r["asset_id"],
                "file": fn,
                "name": r["name"],
                "skill": skill,
                # Two hands is `equip_slots` naming both, which is how the source states it.
                "twoHanded": sorted(r.get("equip_slots") or []) == ["LHELD", "RHELD"],
                "weight": r.get("weight"),
                "levelReq": r.get("level_req"),
                "lengthM": round(longest / UNITS_PER_METRE, 4) if longest else None,
                "size": [d.get("width"), d.get("height"), d.get("depth")] if d else None,
                "min": d.get("min"),
                "max": d.get("max"),
            }
        )

    manifest.sort(key=lambda m: (str(m["skill"]), m["name"]))
    print(f"weapons: {len(manifest)}   missing models: {len(missing)}   total {total / 1024 / 1024:.1f} MB")
    if missing:
        print(f"  missing: {missing[:10]}")

    if args.dry_run:
        return

    os.makedirs(args.out, exist_ok=True)
    for entry in manifest:
        shutil.copy2(os.path.join(ITEMS, entry["file"]), os.path.join(args.out, entry["file"]))
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf8") as fh:
        json.dump({"unitsPerMetre": UNITS_PER_METRE, "weapons": manifest}, fh, indent=0)
    print(f"wrote {len(manifest)} models and manifest.json to {args.out}")


if __name__ == "__main__":
    main()
