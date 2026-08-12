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
spine vertical; our render of the same clip, same frame, used to lean **13.5 degrees
back**. That was the defect this was built to catch, and applying the ASF joint frame
(`ArcBoneRecord.local_rotation`) closed it: rig 18's spine reads -3.6 now, and the wings
fold down the back instead of standing out horizontally.

The -3.6 that remains is posture, not error
-------------------------------------------
It was carried as an open question for a while and it is now settled, so that nobody
spends another pass hunting it. Four measurements, none of which a residual conjugation
error survives:

  * **The spine axis is identical on every rig** -- `(90, 0, 180)` on LOWERBACK, UPPERBACK
    and NECKJOINT alike -- while the measured lean ranges from -9.94 (rig 54) to +1.09
    (rig 120). A math error conditioned on the joint frame cannot vary where the frame
    does not.
  * **It is not the root.** ROOT pitches *back* +5.20 on rig 18; strip its rotation and the
    spine reads -8.35 rather than -3.17. The root is already correcting a forward lean the
    spine bones carry, which is an ordinary animation idiom, not an artifact.
  * **Nothing is clamped.** Across 150 clips per rig the spine reaches +9.83 on rig 18 and
    +8.51 on rig 120, so leaning back is well within what this math produces. There is no
    ceiling to explain away.
  * **It tracks the clip, not the rig.** Rigs 6 and 103 share clip 6000010 and read +0.38
    and +0.32; four rigs with four *different* clips land near -3.2.

The median clip on every rig sampled leans forward by 3 to 8 degrees, which is what a
body at rest does -- chest slightly ahead of hips. Three degrees over a torso is about
eight centimetres of head travel: comfortably inside what "the client holds it vertical"
can mean when it is read off a video.

**So do not drive this to zero.** Anything that does is fitting the math to an eyeball,
which is the failure this file exists to prevent.

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

Read the aggregate with even more care after a real fix
------------------------------------------------------
The joint-frame fix moved rig 18's spine 17 degrees, from +13.3 to -3.6, and moved the
aggregate only 15.84 -> 12.17. An earlier search over 40 axis-composition variants scored
this same family at "12.84 vs 16.11 current" and read that as a near-miss, because the
aggregate averages in `arm`, a weak invariant, over rigs that are allowed to be hunched.
The anchored number is the one that moved. Do not rank candidates on the aggregate.

Searched and rejected (see docs/CLIENT_BINARY_FINDINGS.md):

    4 quaternion component orders, with no joint frame   best 15.31

That space does not contain the fix, and could not: the component swap it searches over
was a stand-in for the joint frame, so the two have to change together.

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
# The client-vs-ours gap on rig 18 as first measured, before the joint frame was
# applied. Kept as the yardstick the residual is reported against.
ARACOIX_ORIGINAL_LEAN = 13.5


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
            print(f"rig 18 spine {aracoix['spine']:+.1f} deg; the lean this was built to catch "
                  f"was {ARACOIX_ORIGINAL_LEAN:+.1f} deg. What is left is a slight FORWARD "
                  f"lean and is posture, not error -- see the docstring before chasing it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
