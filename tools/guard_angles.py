"""What the original client's characters actually did with their arms, in our own angle convention.

`D-134` established that the legacy motion capture is readable and that it contains no two-handed
guard. It also left a thread: our **one-handed** guard was derived in `D-089`/`D-090` from
`Sword_Regular_A` — a clip from a *different* game's animation pack — while the original's own clips
sat unread. Where the two disagree is worth knowing.

So this takes the stillest clips the original has (an idle is a guard held), runs the same forward
kinematics `export_motions.py` validated, and reports the right arm as `poseCharacter` would state
it:

  armR   shoulder pitch, where `rotateX(a)` points the limb along (0, -cos a, -sin a)
  elbowR the additional bend at the elbow, in the same terms

Two conventions have to be reconciled and both are stated rather than assumed. The legacy skeleton
has **+Y up** — checked, the head sits 1.64 above the root and the feet 3.0 below — and **+Z
forward**, which follows from `BACKSHEATHSPACER` pointing its back sheath along -Z. Ours has -Z
forward. So Z is negated on the way in; getting that backwards would mirror every angle and report a
character leaning back as leaning forward.

    python tools/guard_angles.py --top 8
"""

from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from export_motions import bone_table, load_motions, load_skeletons, pose_frame  # noqa: E402

HUMANOID = 1


def arm_angles(pose: dict[str, list[float]]) -> tuple[float, float, float] | None:
    """`armR`, `elbowR` and the hand's height below the shoulder, in our convention."""
    for name in ("RHUMERUS", "RRADIUS", "RHAND"):
        if name not in pose:
            return None
    shoulder, elbow, hand = pose["RHUMERUS"], pose["RRADIUS"], pose["RHAND"]

    def limb(a: list[float], b: list[float]) -> tuple[float, float, float]:
        # Their +Z is forward and ours is -Z, so Z flips on the way in.
        dx, dy, dz = b[0] - a[0], b[1] - a[1], -(b[2] - a[2])
        n = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        return dx / n, dy / n, dz / n

    _, uy, uz = limb(shoulder, elbow)
    _, fy, fz = limb(elbow, hand)
    # `rotateX(θ)` points along (0, -cos θ, -sin θ), so θ = atan2(-z, -y).
    upper = math.atan2(-uz, -uy)
    fore = math.atan2(-fz, -fy)
    bend = fore - upper
    while bend > math.pi:
        bend -= 2 * math.pi
    while bend < -math.pi:
        bend += 2 * math.pi
    return upper, bend, shoulder[1] - hand[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=8, help="how many of the stillest clips to report")
    ap.add_argument("--samples", type=int, default=10)
    args = ap.parse_args()

    skeletons = load_skeletons()
    motions = load_motions()
    bones = bone_table(skeletons[HUMANOID])
    wanted = sorted(set(skeletons[HUMANOID].motion_tokens))

    rows = []
    for clip_id in wanted:
        frames = motions.get(clip_id)
        if frames is None or "RHAND" not in frames["bones"]:
            continue
        count = frames["frame_count"]
        step = max(1, count // args.samples)
        sampled = list(range(0, count, step))[: args.samples]
        poses = [pose_frame(bones, frames["bones"], f) for f in sampled]

        angles = [arm_angles(p) for p in poses]
        angles = [a for a in angles if a is not None]
        if not angles:
            continue

        # Stillness, measured on the hand relative to the root: an idle is a guard being held, and a
        # guard is the thing we are trying to compare against.
        travel = 0.0
        previous = None
        for p in poses:
            local = [p["RHAND"][i] - p["ROOT"][i] for i in range(3)]
            if previous is not None:
                travel += math.dist(local, previous)
            previous = local
        travel /= max(1, len(poses) - 1)

        arm = sum(a[0] for a in angles) / len(angles)
        elbow = sum(a[1] for a in angles) / len(angles)
        drop = sum(a[2] for a in angles) / len(angles)
        rows.append((travel, clip_id, count, arm, elbow, drop))

    rows.sort()
    print(f"\n{len(rows)} humanoid clips. Stillest first — an idle is a guard being held.\n")
    print(f"  {'clip':>10} {'frames':>6} {'travel':>7} {'armR':>7} {'elbowR':>7} {'hand below':>11}")
    print("  " + "-" * 60)
    for travel, clip_id, count, arm, elbow, drop in rows[: args.top]:
        print(f"  {clip_id:>10} {count:>6} {travel:>7.3f} {arm:>7.2f} {elbow:>7.2f} {drop:>11.2f}")

    # Averaging the stillest is meaningless: they are not all the same pose. Some hang the arm, some
    # hold a hand forward, some fold it back, and a mean over that is a number describing nobody.
    # What separates them is where the hand ends up, so classify on that.
    hanging = [r for r in rows if r[5] > 0.8]
    raised = [r for r in rows if r[5] < 0.2]

    def summarise(label: str, group: list[tuple[float, int, int, float, float, float]]) -> None:
        if not group:
            print(f"\n  {label}: none")
            return
        arm = sum(r[3] for r in group) / len(group)
        elbow = sum(r[4] for r in group) / len(group)
        spread = max(abs(r[3] - arm) for r in group)
        print(
            f"\n  {label}: {len(group)} clips\n"
            f"    armR {arm:>6.2f}   elbowR {elbow:>6.2f}   worst armR spread {spread:.2f}"
        )

    summarise("hand HANGING, 0.8+ below the shoulder", hanging)
    summarise("hand UP, at or above the shoulder", raised)

    if rows:
        print("\n  ours, for comparison:")
        print("    WEAPON_GUARD_ARM   0.45     (a drawn weapon, from Sword_Regular_A)")
        print("    WEAPON_GUARD_ELBOW 0.85")
        print("    FIST_GUARD_ARM     0.32     (bare hands)")
        print("    FIST_GUARD_ELBOW   2.05")


if __name__ == "__main__":
    main()
