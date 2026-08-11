"""Export Shadowbane's motion clips as per-bone quaternion tracks, at the source's own frame rate.

Why this exists
---------------
`export_motions.py` writes two files and neither can be played:

  * `motions/clips.json` is **wrong** — 11 joints per clip, each holding a byte-identical copy of the
    ROOT translation track, the per-bone quaternions dropped. It is renamed `clips.BROKEN.json`.
  * `motions/poses.json` is right but is *sampled world positions*, built to describe a clip rather
    than to drive one. Reconstructing rotations from sampled positions is lossy and pointless when
    the source ships them.

This writes the thing a player needs: **per bone, per frame, the quaternion**, at full rate, keyed by
the bone names `rig/skeletons.json` already uses, with unanimated bones omitted and the frame rate
stated.

    python tools/export_motion_tracks.py                      # every skeleton
    python tools/export_motion_tracks.py --skeletons 1,47     # the two wanted first
    python tools/export_motion_tracks.py --decimals 3         # smaller, still far below perceptible

The frame rate, which nothing had
---------------------------------
`ArcMotion` was skipping 27 bytes between the frame count and the bone count. The first eight state
the time base: an int32 **frames per second** at offset 0 and a float32 **seconds per frame** at
offset 4, each other's exact reciprocal. Over all 1,503 clips: **1,483 at 15 fps, 20 at 120 fps, and
zero where the two disagree.** Clip lengths then fall out at 0.07 s to 18.87 s, median 1.73 s. It is
carried per clip here because it genuinely varies.

Size, which was the stated blocker
----------------------------------
Three things, none of them lossy in a way a renderer can resolve:

  * **Absent bones are omitted.** A clip animates a subset — 28 of skeleton 1's 43 — and the rest are
    held at their bind pose by the consumer.
  * **Constant tracks collapse to one entry.** A bone whose position never changes writes three
    numbers rather than three per frame. This is *lossless*: `"pos": [x, y, z]` against
    `"posFrames": n` is exactly the repeated value. Scale is constant on essentially everything and
    position on everything except the root, so this is most of the saving.
  * **Rounding.** Four decimals on a normalised quaternion is about 0.006 degrees.

A track is written flat — `[x, y, z, w, x, y, z, w, ...]` — rather than as a list of lists, because
the brackets cost more than the numbers at this size.

Output
------
  motions/tracks/index.json          every skeleton, its clips, and what this run wrote
  motions/tracks/<skeletonId>.json   one per skeleton: bone count and the tokens it plays
  motions/tracks/clips/<token>.json  one per clip: the tracks

**Each clip is written once**, not once per skeleton that plays it. The 103 skeletons name 10,435
tokens between them for 1,503 distinct clips, so inlining would write most clips about seven times —
`--inline` does exactly that and is right for one or two skeletons wanted self-contained. A clip's
tracks do not depend on which skeleton plays them: the bone names are the source's own.

Measured, the whole set is **45 MB over 1,423 clip files**, which is why this does not sample.
Not one blob, because the consumer reads `graph/assets/*.json` as 9,924 separate files quite happily.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arcane.ArcMotion import ArcMotion
from arcane.util.ArcFileCache import load_cache_file
from arcane.util.ResStream import ResStream

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "arcane_dump")
MOTION_CACHE = os.path.join(CACHE, "Motion", "Motion.cache")
SKELETONS_JSON = os.path.join(ROOT, "export_aegisfall", "rig", "skeletons.json")

# The rates the source actually uses, so a clip carrying anything else is reported rather than
# written silently.
KNOWN_RATES = (15, 120)


def load_clips() -> dict[int, dict[str, Any]]:
    """Every clip in `Motion.cache` that decodes to real per-bone tracks, keyed by motion token."""
    out: dict[int, dict[str, Any]] = {}
    for index, entry in enumerate(load_cache_file(MOTION_CACHE)):
        key, data = (entry[0], entry[1]) if isinstance(entry, (list, tuple)) else (index, entry)
        motion = ArcMotion()
        try:
            motion.load_binary(ResStream(data))
        except Exception:  # noqa: BLE001
            continue
        frames = getattr(motion, "frames", None)
        if isinstance(frames, dict) and frames.get("bones"):
            frames = dict(frames)
            frames["name"] = getattr(motion, "motion_file", "")
            out[key] = frames
    return out


def constant(track: list[list[float]]) -> bool:
    """Whether every frame of this track holds the same value.

    Compared on the **rounded** values, because that is what is written: a track that differs only in
    the digits this export discards is constant as far as the file is concerned, and collapsing it
    stays lossless with respect to the output.
    """
    if len(track) <= 1:
        return True
    first = track[0]
    return all(all(a == b for a, b in zip(frame, first)) for frame in track[1:])


def round_track(track: list[list[float]], decimals: int) -> list[list[float]]:
    return [[round(v, decimals) for v in frame] for frame in track]


def flatten(track: list[list[float]]) -> list[float]:
    return [v for frame in track for v in frame]


def build_clip(clip: dict[str, Any], skeleton_bones: set[str], decimals: int) -> dict[str, Any]:
    """One clip as tracks, with constant channels collapsed and absent bones simply not present."""
    frame_count = int(clip.get("frame_count") or 0)
    fps = int(clip.get("fps") or 0)
    spf = float(clip.get("seconds_per_frame") or 0.0)

    bones: dict[str, Any] = {}
    unknown: list[str] = []
    for name, channels in clip["bones"].items():
        if name not in skeleton_bones:
            # Reported rather than dropped in silence: a clip naming a bone its skeleton does not
            # have means the token mapping is wrong, and that is worth failing loudly over.
            unknown.append(name)
        entry: dict[str, Any] = {}
        for key, source in (("rot", "rot"), ("pos", "pos"), ("scale", "scale")):
            values = channels.get(source) or []
            if not values:
                continue
            rounded = round_track(values, decimals)
            if constant(rounded):
                # One value stands for every frame. Named without the `Frames` suffix so a reader
                # can tell the two apart structurally rather than by measuring the length.
                entry[key] = rounded[0]
            else:
                entry[key + "Frames"] = flatten(rounded)
        if entry:
            bones[name] = entry

    return {
        "name": clip.get("name", ""),
        "frames": frame_count,
        "fps": fps,
        "secondsPerFrame": round(spf, 6),
        "seconds": round(frame_count / fps, 4) if fps > 0 else None,
        "bones": bones,
        **({"unknownBones": unknown} if unknown else {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skeletons",
        default="",
        help="comma-separated skeleton ids; empty means every skeleton in skeletons.json",
    )
    parser.add_argument("--decimals", type=int, default=4, help="rounding for every channel")
    parser.add_argument(
        "--inline",
        action="store_true",
        help=(
            "write each skeleton's clips into its own file, self-contained. Convenient for a few "
            "skeletons and wasteful for all of them: the 103 skeletons name 10,435 tokens between "
            "them for 1,503 distinct clips, so inlining writes most clips about seven times. The "
            "default writes each clip once under clips/ and gives each skeleton a token list."
        ),
    )
    parser.add_argument(
        "--out",
        default=os.path.join(ROOT, "export_aegisfall", "motions", "tracks"),
        help="output directory",
    )
    args = parser.parse_args()

    if not os.path.exists(SKELETONS_JSON):
        sys.exit(f"no {SKELETONS_JSON} — run tools/export_skeletons.py first")

    with open(SKELETONS_JSON, encoding="utf-8") as handle:
        skeletons = json.load(handle)["skeletons"]

    wanted = (
        [s.strip() for s in args.skeletons.split(",") if s.strip()]
        if args.skeletons
        else list(skeletons)
    )
    missing = [s for s in wanted if s not in skeletons]
    if missing:
        sys.exit(f"skeletons.json has no {', '.join(missing)}")

    print(f"reading {MOTION_CACHE}")
    clips = load_clips()
    print(f"  {len(clips)} clips decode to per-bone tracks")
    rates = sorted({int(c.get('fps') or 0) for c in clips.values()})
    print(f"  frame rates present: {rates}")
    odd = [k for k, c in clips.items() if int(c.get("fps") or 0) not in KNOWN_RATES]
    if odd:
        print(f"  !! {len(odd)} clips carry a rate outside {KNOWN_RATES}: {odd[:8]}")

    os.makedirs(args.out, exist_ok=True)
    clips_dir = os.path.join(args.out, "clips")
    if not args.inline:
        os.makedirs(clips_dir, exist_ok=True)
    # token -> bytes on disk, so a clip named by several skeletons is written once and counted once.
    clips_on_disk: dict[int, int] = {}

    index: dict[str, Any] = {}
    total_bytes = 0
    total_clips = 0
    missing_tokens: set[int] = set()

    for skeleton_id in wanted:
        skeleton = skeletons[skeleton_id]
        bone_names = {b["name"] if isinstance(b, dict) else b for b in skeleton["bones"]}
        # `motionTokens` repeats — skeleton 1 lists 247 for 234 distinct — so the set is what is
        # written and the count of both is reported rather than one standing in for the other.
        tokens = list(dict.fromkeys(skeleton.get("motionTokens", [])))

        written: dict[str, Any] = {}
        held: list[int] = []
        for token in tokens:
            clip = clips.get(token)
            if clip is None:
                missing_tokens.add(token)
                continue
            held.append(token)
            built = build_clip(clip, bone_names, args.decimals)
            if args.inline:
                written[str(token)] = built
            elif token not in clips_on_disk:
                # Written once, under the first skeleton that names it. A clip's tracks are the same
                # data whichever skeleton plays it — the bone names are the source's own, not a
                # per-skeleton numbering — so a second copy would be a byte-for-byte duplicate.
                path = os.path.join(clips_dir, f"{token}.json")
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(built, handle, separators=(",", ":"))
                clips_on_disk[token] = os.path.getsize(path)

        payload = {
            "generator": "tools/export_motion_tracks.py",
            "skeletonId": int(skeleton_id),
            "boneCount": skeleton.get("boneCount", len(bone_names)),
            "note": (
                "Per bone, per frame, at the clip's own frame rate. A channel written as `rot` is "
                "constant for the whole clip; `rotFrames` is flat, four numbers per frame. Bones "
                "absent from a clip are absent here and should be held at their bind pose."
            ),
            "decimals": args.decimals,
            "clipCount": len(written) if args.inline else len(held),
            **(
                {"clips": written}
                if args.inline
                else {"clips": held, "clipDir": "clips", "clipFile": "clips/<token>.json"}
            ),
        }
        path = os.path.join(args.out, f"{skeleton_id}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
        size = os.path.getsize(path)
        total_bytes += size
        total_clips += len(written) if args.inline else len(held)
        index[skeleton_id] = {
            "file": f"{skeleton_id}.json",
            "boneCount": payload["boneCount"],
            "clipCount": len(written) if args.inline else len(held),
            "tokensListed": len(skeleton.get("motionTokens", [])),
            "tokensDistinct": len(tokens),
            "bytes": size,
        }
        print(
            f"  skeleton {skeleton_id:>4}: "
            f"{(len(written) if args.inline else len(held)):>4} clips of {len(tokens):>4} tokens"
            f"  {size / 1_048_576:8.2f} MB"
        )

    # Clips no skeleton names. 80 of the 1,503, and they are written rather than dropped: the ask
    # was for everything if size allows, and a clip nobody currently references is exactly the kind
    # of thing that turns out to be an emote once somebody looks. Listed separately so they cannot
    # be mistaken for a skeleton's own set.
    orphans: list[int] = []
    if not args.inline and not args.skeletons:
        claimed = {t for s in skeletons.values() for t in s.get("motionTokens", [])}
        for token, clip in clips.items():
            if token in claimed or token in clips_on_disk:
                continue
            # No skeleton to check the names against, so nothing is called unknown here.
            built = build_clip(clip, set(clip["bones"]), args.decimals)
            path = os.path.join(clips_dir, f"{token}.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(built, handle, separators=(",", ":"))
            clips_on_disk[token] = os.path.getsize(path)
            orphans.append(token)

    with open(os.path.join(args.out, "index.json"), "w", encoding="utf-8") as handle:
        json.dump(
            {
                "generator": "tools/export_motion_tracks.py",
                "note": (
                    "One file per clip under clips/, named by motion token. Each skeleton's file "
                    "lists the tokens it plays. A channel named `rot` is constant for the whole "
                    "clip; `rotFrames` is flat, four numbers per frame. Bones absent from a clip "
                    "are not animated by it and should be held at their bind pose. `fps` is stated "
                    "by the clip itself."
                ),
                "clipsInCache": len(clips),
                "clipSlotsAcrossSkeletons": total_clips,
                "layout": "inline" if args.inline else "deduplicated",
                "distinctClipFiles": len(clips_on_disk),
                "clipBytes": sum(clips_on_disk.values()),
                "unreferencedClips": sorted(orphans),
                "tokensWithNoClip": sorted(missing_tokens),
                "skeletons": index,
            },
            handle,
            indent=2,
        )

    clip_bytes = sum(clips_on_disk.values())
    print(
        f"\n{total_clips} clip slots over {len(wanted)} skeletons, "
        f"{len(clips_on_disk) or total_clips} distinct clips written"
    )
    if orphans:
        print(f"  including {len(orphans)} clips no skeleton references")
    print(f"  {(total_bytes + clip_bytes) / 1_048_576:.1f} MB total")
    if missing_tokens:
        # A token a skeleton claims and the cache does not hold. Named, because a silent skip here
        # is a clip the consumer will look for and not find.
        print(f"  {len(missing_tokens)} tokens named by a skeleton had no clip in the cache")
    print(f"written to {args.out}")


if __name__ == "__main__":
    main()
