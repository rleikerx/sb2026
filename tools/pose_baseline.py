#!/usr/bin/env python3
"""
Freeze every playable race's pose as numbers, so a change to the pose math is measured.

Why this exists
---------------
A pose regression is invisible at thumbnail size. Applying the ASF `axis` frame as
`C * M * C^-1` moves rig 1 by 0.169 stature units -- seventeen percent of body height,
enough to swing a human's arms from hanging to splayed -- and it was reported here as
"unchanged" from a contact sheet, twice, because small pictures of a standing figure
all look like a standing figure. See docs/CLIENT_BINARY_FINDINGS.md section 4.

So: record joint positions, not impressions. Every joint of every playable race at its
idle clip, normalised by that rig's own stature so the numbers compare across a Centaur
and a Dwarf. Re-run after a change and the diff is a table, in one command.

    python tools/pose_baseline.py --write        # freeze the current pose math
    python tools/pose_baseline.py                # compare against the frozen baseline

Exit status is 1 if any rig moved more than --tolerance, so it can gate a commit.

Scope is the playable races on purpose: twelve races over eight rigs is small enough to
run in seconds and covers every body plan a player sees. `--all-creature-rigs` widens it
to all 85 rigs the creature export uses, which is the right check before shipping a pose
change but too slow to run constantly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_BASELINE = REPO_ROOT / "docs" / "pose_baseline.json"
# The low band holds the idle/stance clips; take the first slot a rig actually fills.
IDLE_SLOTS = ("10", "11", "12", "13", "1")


def load_inputs(export: Path):
    resolve = json.loads((export / "animations" / "resolve.json").read_text())["skeletons"]
    races = json.loads((export / "content" / "races.json").read_text())
    return resolve, races


def variants(races, playable_only=True):
    """(label, asset_id, skeleton_id) for each race variant worth posing."""
    out = []
    for race in sorted(races, key=lambda r: r["race"]):
        if playable_only and not race.get("standard_creation"):
            continue
        seen = set()
        for v in race.get("variants", []):
            key = (v.get("sex"), v.get("skeleton_id"))
            if key in seen or v.get("skeleton_id") is None:
                continue
            seen.add(key)
            out.append((f"{race['race']} {str(v.get('sex') or '?')[0]}",
                        v["asset_id"], v["skeleton_id"]))
    return out


def idle_pose(am, resolve, skeleton_id):
    """The rig's own idle frame, or its stance pose if it has no low-band clip."""
    slots = resolve.get(str(skeleton_id), {}).get("animid", {})
    for slot in IDLE_SLOTS:
        token = slots.get(slot)
        if not token:
            continue
        pose = am.load_motion_pose(token, 0)
        if pose:
            return pose, f"clip {token}"
    am._stand_poses.pop(skeleton_id, None)
    return am.stand_pose(skeleton_id), "stand_pose"


def measure(am, skeleton_id, pose) -> Dict[str, Any]:
    """Every joint position in stature units, with the rig's own scale recorded."""
    skeleton = am.load_skeleton(skeleton_id)
    resolved = skeleton.pose(pose)
    ys = [entry[1][1] for entry in resolved.values()]
    stature = (max(ys) - min(ys)) or 1.0
    floor = min(ys)
    joints = {}
    for name, (_rot, start) in resolved.items():
        joints[name] = [round((start[0]) / stature, 5),
                        round((start[1] - floor) / stature, 5),
                        round((start[2]) / stature, 5)]
    return {"stature": round(stature, 5), "joints": joints}


def collect(export: Path, playable_only: bool) -> Dict[str, Any]:
    from assets.asset_manager import AssetManager

    resolve, races = load_inputs(export)
    am = AssetManager(str(REPO_ROOT / "arcane_dump"))
    rows: Dict[str, Any] = {}
    for label, _asset_id, skeleton_id in variants(races, playable_only):
        try:
            pose, source = idle_pose(am, resolve, skeleton_id)
            row = measure(am, skeleton_id, pose)
        except Exception as error:  # noqa: BLE001 - a rig that will not pose is a finding
            rows[label] = {"error": f"{type(error).__name__}: {error}"}
            continue
        row["skeleton"] = skeleton_id
        row["source"] = source
        rows[label] = row
    return rows


def compare(old: Dict[str, Any], new: Dict[str, Any], tolerance: float):
    """Per-rig max and mean joint displacement, in stature units."""
    report: List[tuple] = []
    for label, now in sorted(new.items()):
        before = old.get(label)
        if before is None:
            report.append((label, None, None, "NEW"))
            continue
        if "error" in now or "error" in before:
            report.append((label, None, None, now.get("error") or "was error"))
            continue
        shared = set(before["joints"]) & set(now["joints"])
        gone = set(before["joints"]) - shared
        if not shared:
            report.append((label, None, None, "no common joints"))
            continue
        deltas = []
        for name in shared:
            a, b = before["joints"][name], now["joints"][name]
            deltas.append(sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5)
        note = f"{len(gone)} joints missing" if gone else ""
        report.append((label, max(deltas), sum(deltas) / len(deltas), note))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default=str(REPO_ROOT / "export_aegisfall"))
    ap.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    ap.add_argument("--write", action="store_true", help="freeze current output as the baseline")
    ap.add_argument("--all-creature-rigs", action="store_true",
                    help="every race rune, not just the playable twelve")
    ap.add_argument("--tolerance", type=float, default=0.002,
                    help="stature units a joint may move before it is a regression")
    args = ap.parse_args()

    baseline = Path(args.baseline)
    rows = collect(Path(args.export), playable_only=not args.all_creature_rigs)

    if args.write:
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(json.dumps(
            {"note": "joint positions in stature units; see tools/pose_baseline.py",
             "tolerance": args.tolerance, "rigs": rows}, indent=1), encoding="utf-8")
        joints = sum(len(r.get("joints", {})) for r in rows.values())
        print(f"froze {len(rows)} rigs, {joints} joints -> {baseline}")
        return 0

    if not baseline.exists():
        print(f"no baseline at {baseline}; run with --write first", file=sys.stderr)
        return 2

    old = json.loads(baseline.read_text())["rigs"]
    report = compare(old, rows, args.tolerance)
    worst = 0.0
    print(f"{'rig':<16} {'maxMove':>9} {'meanMove':>9}  note")
    for label, mx, mean, note in report:
        if mx is None:
            print(f"{label:<16} {'-':>9} {'-':>9}  {note}")
            continue
        worst = max(worst, mx)
        flag = "  <-- REGRESSION" if mx > args.tolerance else ""
        print(f"{label:<16} {mx:9.5f} {mean:9.5f}  {note}{flag}")
    print(f"\nworst movement {worst:.5f} stature units (tolerance {args.tolerance})")
    return 1 if worst > args.tolerance else 0


if __name__ == "__main__":
    raise SystemExit(main())
