"""Export Shadowbane's motion clips with the joint rotations intact, and describe them.

Why this exists
---------------
`export_aegisfall/motions/clips.json` is wrong. It carries 11 joints per clip and every one of them
holds a byte-identical copy of the ROOT translation track — the per-bone quaternions were dropped
entirely. That is also why the `spread` field in its `descriptors.json` is 0.0 on all 1,121 clips:
`spread` is a hands-apart measure, both hands resolved to the same point, so the two-handed tell it
was built to find could never fire. The zeros were the export's fault, not the measurement's.

`ArcMotion` already decodes the real thing: per bone, per frame, a position, a quaternion and a
scale. `ArcSkeleton` supplies the hierarchy and the rest offsets. This walks both, runs forward
kinematics, and writes two files:

  motions/skeletons.json   one entry per skeleton: bone names, parents, offsets, lengths
  motions/poses.json       per clip, per sampled frame, the world position of every joint

`poses.json` is written for one skeleton at a time — the full 1,503 clips at every frame would be
hundreds of megabytes and nobody needs it. Sampling and a skeleton filter keep it to something a
person can actually read and a repository can hold.

    python tools/export_motions.py --skeleton 1 --samples 12 --out export_aegisfall/motions

It also prints a descriptor table, sorted by how close the two hands are, because that is the
question this was built to answer: which of these clips is a two-handed hold?
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arcane.ArcMotion import ArcMotion
from arcane.ArcSkeleton import ArcSkeleton, _euler_to_mat, _mat_mul, _mat_transpose
from arcane.util.ArcFileCache import load_cache_file
from arcane.util.ResStream import ResStream

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "arcane_dump")
MOTION_CACHE = os.path.join(CACHE, "Motion", "Motion.cache")
SKELETON_CACHE = os.path.join(CACHE, "Skeleton", "Skeleton.cache")


# ───────────────────────────── maths ─────────────────────────────
#
# Kept to plain lists rather than numpy: this runs once, over a few hundred clips, and a dependency
# that has to be present for a one-shot export is a dependency that will not be present.


def quat_to_matrix(q: list[float]) -> list[float]:
    """A quaternion (x, y, z, w) as a row-major 3x3, flattened."""
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n < 1e-9:
        return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    x, y, z, w = x / n, y / n, z / n, w / n
    return [
        1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
        2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
        2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y),
    ]


def compose(parent: tuple[list[float], list[float]],
            rotation: list[float],
            offset: list[float]) -> tuple[list[float], list[float]]:
    """`parent · translate(offset) · rotate(rotation)`, as (3x3, translation)."""
    pr, pt = parent
    # The offset is expressed in the parent's frame, so it rotates by the parent before it adds.
    t = [
        pt[0] + pr[0] * offset[0] + pr[1] * offset[1] + pr[2] * offset[2],
        pt[1] + pr[3] * offset[0] + pr[4] * offset[1] + pr[5] * offset[2],
        pt[2] + pr[6] * offset[0] + pr[7] * offset[1] + pr[8] * offset[2],
    ]
    r = [
        pr[0] * rotation[0] + pr[1] * rotation[3] + pr[2] * rotation[6],
        pr[0] * rotation[1] + pr[1] * rotation[4] + pr[2] * rotation[7],
        pr[0] * rotation[2] + pr[1] * rotation[5] + pr[2] * rotation[8],
        pr[3] * rotation[0] + pr[4] * rotation[3] + pr[5] * rotation[6],
        pr[3] * rotation[1] + pr[4] * rotation[4] + pr[5] * rotation[7],
        pr[3] * rotation[2] + pr[4] * rotation[5] + pr[5] * rotation[8],
        pr[6] * rotation[0] + pr[7] * rotation[3] + pr[8] * rotation[6],
        pr[6] * rotation[1] + pr[7] * rotation[4] + pr[8] * rotation[7],
        pr[6] * rotation[2] + pr[7] * rotation[5] + pr[8] * rotation[8],
    ]
    return r, t


IDENTITY = ([1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 0.0])


# ───────────────────────────── loading ─────────────────────────────


def load_skeletons() -> dict[int, Any]:
    out: dict[int, Any] = {}
    for index, entry in enumerate(load_cache_file(SKELETON_CACHE)):
        key, data = (entry[0], entry[1]) if isinstance(entry, (list, tuple)) else (index, entry)
        try:
            skel = ArcSkeleton()
            skel.load_binary(ResStream(data))
        except Exception:  # noqa: BLE001
            continue
        if skel.bones:
            out[key] = skel
    return out


def load_motions() -> dict[int, Any]:
    out: dict[int, Any] = {}
    for index, entry in enumerate(load_cache_file(MOTION_CACHE)):
        key, data = (entry[0], entry[1]) if isinstance(entry, (list, tuple)) else (index, entry)
        try:
            motion = ArcMotion()
            motion.load_binary(ResStream(data))
        except Exception:  # noqa: BLE001
            continue
        frames = getattr(motion, "frames", None)
        if isinstance(frames, dict) and frames.get("bones"):
            out[key] = frames
    return out


def bone_table(skel: Any) -> list[dict[str, Any]]:
    """Name, parent and rest offset per bone. The offset is the bind matrix's translation, which is
    row-major here — `LHIPJOINT` reads 0.224 at index 3 against a `dir` of (1,0,0) and a length of
    0.224, which is the check that says row-major rather than column."""
    table = []
    for b in skel.bones:
        m = b.bind_pose_matrix
        offset = [m[3], m[7], m[11]] if len(m) == 16 else [0.0, 0.0, 0.0]
        table.append(
            {
                "name": b.name,
                "parent": b.parent_index,
                "offset": [round(v, 6) for v in offset],
                "length": round(b.length, 6),
                # The joint's own frame, which the clip's quaternions are stated in.
                "axis": [round(float(v), 6) for v in b.axis],
            }
        )
    return table


def pose_frame(bones: list[dict[str, Any]], tracks: dict[str, Any], frame: int) -> dict[str, list[float]]:
    """World position of every bone at one frame."""
    world: list[tuple[list[float], list[float]]] = []
    out: dict[str, list[float]] = {}
    for i, bone in enumerate(bones):
        parent = IDENTITY if bone["parent"] < 0 else world[bone["parent"]]
        track = tracks.get(bone["name"])
        if track is None:
            rotation = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
            offset = bone["offset"]
        else:
            f = min(frame, len(track["rot"]) - 1)
            # Out of the joint frame before composing with the parent, the same
            # `C * R * C^-1` that `ArcBoneRecord.local_rotation` applies. Walking
            # the hierarchy here rather than calling `ArcSkeleton.pose` means this
            # step has to be repeated, and leaving it out is what tipped every
            # exported clip backwards.
            rotation = quat_to_matrix(track["rot"][f])
            axis = bone.get("axis") or (0.0, 0.0, 0.0)
            if any(axis):
                frame_matrix = _euler_to_mat(axis)
                rotation = list(_mat_mul(_mat_mul(frame_matrix, tuple(rotation)),
                                         _mat_transpose(frame_matrix)))
            # Only the root translates; every other bone sits at its rest offset and turns.
            offset = track["pos"][f] if bone["parent"] < 0 else bone["offset"]
        node = compose(parent, rotation, offset)
        world.append(node)
        out[bone["name"]] = [round(v, 5) for v in node[1]]
    return out


# ───────────────────────────── description ─────────────────────────────


def describe(poses: list[dict[str, list[float]]]) -> dict[str, float]:
    """The measures that separate a two-handed hold from everything else.

    `handsApart` is the one that matters and the one the previous export could never produce: with
    every joint carrying the root's track, both hands sat at the same point and it was always zero.
    """

    def dist(a: list[float], b: list[float]) -> float:
        return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))

    gaps, highs, forwards, travel = [], [], [], []
    previous = None
    for p in poses:
        lh, rh = p.get("LHAND"), p.get("RHAND")
        root = p.get("ROOT", [0.0, 0.0, 0.0])
        if lh is None or rh is None:
            continue
        gaps.append(dist(lh, rh))
        mid = [(lh[i] + rh[i]) / 2 for i in range(3)]
        highs.append(mid[1] - root[1])
        forwards.append(mid[2] - root[2])
        # How much the weapon hand moves *relative to the body*, so locomotion does not read as a
        # swing. A guard is nearly still; a strike is not.
        local = [rh[i] - root[i] for i in range(3)]
        if previous is not None:
            travel.append(dist(local, previous))
        previous = local
    if not gaps:
        return {}

    # Arm from the skeleton itself: LHUMERUS→LRADIUS is 0.690 and LRADIUS→LHAND is 0.329 + 0.095.
    # Measured off a posed figure and confirmed against those numbers before anything was concluded.
    reach = 0.690 + 0.329 + 0.095
    # Both hands on one haft. A two-handed grip is a couple of hand-widths, which against a body
    # this size (head 1.64 above root, feet 3.0 below) is well under half an arm.
    together = sum(1 for g in gaps if g < reach * 0.5)
    return {
        "handsApart": round(sum(gaps) / len(gaps), 4),
        "handsApartMin": round(min(gaps), 4),
        "handsApartAsArm": round((sum(gaps) / len(gaps)) / reach, 4),
        # The measure that separates a *hold* from a motion that merely passes through one.
        "togetherFrac": round(together / len(gaps), 3),
        "handMidHeight": round(sum(highs) / len(highs), 4),
        "handMidForward": round(sum(forwards) / len(forwards), 4),
        "handTravel": round(sum(travel) / len(travel), 4) if travel else 0.0,
    }


# ───────────────────────────── main ─────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--skeleton",
        default="1",
        help="which skeleton to export (1 = humanoid), or 'all' to scan every two-armed one",
    )
    ap.add_argument("--samples", type=int, default=12, help="frames sampled per clip")
    ap.add_argument("--out", default=None, help="directory to write skeletons.json / poses.json")
    ap.add_argument("--top", type=int, default=25, help="how many rows of the descriptor table")
    args = ap.parse_args()

    print("loading caches ...")
    skeletons = load_skeletons()
    motions = load_motions()
    print(f"  {len(skeletons)} skeletons, {len(motions)} motion clips decoded")

    if args.skeleton == "all":
        # Every skeleton with two hands. A creature with no arms cannot hold anything two-handed,
        # and scanning it only dilutes the table.
        targets = [
            k
            for k, s in sorted(skeletons.items())
            if {"LHAND", "RHAND"} <= {b.name for b in s.bones}
        ]
        print(f"  scanning {len(targets)} two-armed skeletons: {targets[:12]}{' ...' if len(targets) > 12 else ''}")
    else:
        targets = [int(args.skeleton)]
        if targets[0] not in skeletons:
            raise SystemExit(f"no skeleton {args.skeleton}; have {sorted(skeletons)[:20]}")

    rows = []
    poses_out: dict[str, Any] = {}
    bones_by_skeleton: dict[str, Any] = {}

    for skeleton_id in targets:
        skel = skeletons[skeleton_id]
        bones = bone_table(skel)
        bones_by_skeleton[str(skeleton_id)] = bones
        wanted = sorted(set(skel.motion_tokens))
        if len(targets) == 1:
            print(f"  skeleton {skeleton_id}: {len(bones)} bones, {len(wanted)} distinct motions")

        for clip_id in wanted:
            frames = motions.get(clip_id)
            if frames is None:
                continue
            count = frames["frame_count"]
            tracks = frames["bones"]
            # A clip only means anything on a skeleton whose bones it actually drives.
            if not {"LHAND", "RHAND"} <= set(tracks):
                continue
            step = max(1, count // args.samples)
            sampled = list(range(0, count, step))[: args.samples]
            poses = [pose_frame(bones, tracks, f) for f in sampled]
            d = describe(poses)
            if not d:
                continue
            rows.append({"id": clip_id, "skeleton": skeleton_id, "frames": count, **d})
            poses_out[f"{skeleton_id}:{clip_id}"] = {
                "skeleton": skeleton_id,
                "frames": count,
                "sampled": sampled,
                "poses": poses,
            }

    # Hands together for most of the clip first, and among those the stillest — which is a *hold*
    # rather than a motion that happens to pass through one. Sorting on mean separation alone put a
    # clip at the top whose hands start 1.56 apart and converge, which is a draw, not a guard.
    rows.sort(key=lambda r: (-r["togetherFrac"], r["handTravel"]))

    print(f"\n{len(rows)} clips posed. Two-handed and still first.\n")
    header = (
        f"  {'clip':>10}  {'skel':>5}  {'frames':>6}  {'together':>8}  {'apart':>7}  {'x arm':>6}"
        f"  {'travel':>7}  {'height':>7}  {'fwd':>7}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for r in rows[: args.top]:
        print(
            f"  {r['id']:>10}  {r.get('skeleton', ''):>5}  {r['frames']:>6}  {r['togetherFrac']:>8.2f}"
            f"  {r['handsApart']:>7.3f}  {r['handsApartAsArm']:>6.2f}  {r['handTravel']:>7.3f}"
            f"  {r['handMidHeight']:>7.3f}  {r['handMidForward']:>7.3f}"
        )

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "skeletons.json"), "w", encoding="utf8") as fh:
            json.dump(bones_by_skeleton, fh, indent=1)
        with open(os.path.join(args.out, "poses.json"), "w", encoding="utf8") as fh:
            json.dump({"clips": poses_out, "descriptors": rows}, fh)
        print(f"\nwrote skeletons.json and poses.json to {args.out}")


if __name__ == "__main__":
    main()
