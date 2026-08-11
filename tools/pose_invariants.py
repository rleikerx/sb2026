#!/usr/bin/env python3
"""
Score the pose math against postures the client is known to hold.

Why this exists
---------------
`pose_baseline.py` catches *change*. It cannot say whether a change is an improvement,
which is how a candidate that moved every rig by up to 0.53 stature units got called
correct here twice. This scores *correctness* instead, against angles that have a known
right answer.

The anchor is measured, not assumed. Client video of the Aracoix idle (rig 18) shows the
spine vertical; our render of the same clip, same frame, leans **13.5 degrees back**. That
is a real defect, and it is the case every candidate has to fix.

    spine   LOWERBACK -> NECKJOINT, angle off vertical      target 0
    head    NECK -> HEAD, angle off vertical                target 0
    arm     LHUMERUS -> LRADIUS, angle off hanging down     target 0

Read the aggregate with care
----------------------------
Averaging "distance from upright" across rigs conflates error with posture: a minotaur
may genuinely stand hunched, and driving its score to zero would be wrong. The aggregate
is a search signal, not a specification. **Rig 18 is the only number verified against the
client** -- treat the rest as corroborating, and check a candidate visually before
believing it.

Searched and rejected so far (see docs/CLIENT_BINARY_FINDINGS.md):

    40 axis-composition variants   best 12.84 vs 16.11 current
    4 quaternion component orders  best 15.31 (dropping ArcMotion's ROOT exemption)

Neither space contains the fix.

Usage:
    python tools/pose_invariants.py
    python tools/pose_invariants.py --rigs 1,18 --verbose
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Rigs with a humanoid spine/arm layout, so the invariants mean something. Rig 18 first:
# it is the one anchored to client video.
DEFAULT_RIGS = (18, 1, 6, 54, 103, 120)
IDLE_SLOTS = ("10", "11", "12", "1")
# The measured client-vs-ours gap on rig 18, for reference in the report.
ARACOIX_OBSERVED_LEAN = 13.5


def angle_off_vertical(a, b) -> Optional[float]:
    """Signed angle of b-a away from +Y in the Y/Z plane. Positive leans backward."""
    v = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    if (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5 < 1e-6:
        return None
    return math.degrees(math.atan2(-v[2], v[1]))


def angle_off_down(a, b) -> Optional[float]:
    """Unsigned angle of b-a away from straight down. 0 is a limb hanging."""
    v = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    n = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5
    if n < 1e-6:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, -v[1] / n))))


def measure(resolved) -> Dict[str, float]:
    out: Dict[str, float] = {}
    def pos(name):
        entry = resolved.get(name)
        return entry[1] if entry else None
    pairs = (("spine", "LOWERBACK", "NECKJOINT", angle_off_vertical),
             ("head", "NECK", "HEAD", angle_off_vertical),
             ("arm", "LHUMERUS", "LRADIUS", angle_off_down))
    for key, lo, hi, fn in pairs:
        a, b = pos(lo), pos(hi)
        if a and b:
            value = fn(a, b)
            if value is not None:
                out[key] = value
    return out


def score_rig(am, resolve, skeleton_id, samples: int) -> Optional[Dict[str, float]]:
    slots = resolve.get(str(skeleton_id), {}).get("animid", {})
    token = next((slots[s] for s in IDLE_SLOTS if slots.get(s)), None)
    if token is None:
        return None
    motion = am.load_motion(token)
    data = getattr(motion, "frames", None) if motion else None
    if not data:
        return None
    skeleton = am.load_skeleton(skeleton_id)
    total = max(1, data["frame_count"])
    acc: Dict[str, List[float]] = {}
    for frame in range(0, total, max(1, total // samples)):
        rotations = am.load_motion_pose(token, frame)
        if not rotations:
            continue
        for key, value in measure(skeleton.pose(rotations)).items():
            acc.setdefault(key, []).append(value)
    if not acc:
        return None
    row = {k: sum(v) / len(v) for k, v in acc.items()}
    row["clip"] = token
    row["deviation"] = sum(abs(row[k]) for k in ("spine", "head", "arm") if k in row) / \
                       max(1, sum(1 for k in ("spine", "head", "arm") if k in row))
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default=str(REPO_ROOT / "export_aegisfall"))
    ap.add_argument("--rigs", default=",".join(str(r) for r in DEFAULT_RIGS))
    ap.add_argument("--samples", type=int, default=6, help="frames sampled per clip")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    from assets.asset_manager import AssetManager

    resolve = json.loads(
        (Path(args.export) / "animations" / "resolve.json").read_text())["skeletons"]
    am = AssetManager(str(REPO_ROOT / "arcane_dump"))

    rigs = [int(r) for r in args.rigs.split(",") if r.strip()]
    print("degrees off the posture the client holds; 0 is correct, + spine/head leans back")
    print(f"{'rig':>5} {'clip':>11} {'spine':>8} {'head':>8} {'arm':>8} {'|dev|':>8}")
    rows = []
    for skeleton_id in rigs:
        row = score_rig(am, resolve, skeleton_id, args.samples)
        if row is None:
            print(f"{skeleton_id:>5}  no idle clip")
            continue
        rows.append(row)
        anchor = "  <-- anchored to client video" if skeleton_id == 18 else ""
        print(f"{skeleton_id:>5} {row['clip']:>11} "
              f"{row.get('spine', float('nan')):>8.1f} {row.get('head', float('nan')):>8.1f} "
              f"{row.get('arm', float('nan')):>8.1f} {row['deviation']:>8.2f}{anchor}")

    if rows:
        overall = sum(r["deviation"] for r in rows) / len(rows)
        print(f"\naggregate {overall:.2f} deg  (search signal only -- see the docstring)")
        aracoix = next((r for r in rows if r["clip"] and r.get("spine") is not None
                        and r["clip"] // 1000000 == 18), None)
        if aracoix:
            print(f"rig 18 spine {aracoix['spine']:+.1f} deg; client video shows this vertical, "
                  f"so the defect is about {ARACOIX_OBSERVED_LEAN:.1f} deg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
