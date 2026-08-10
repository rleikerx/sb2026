#!/usr/bin/env python3
"""
Contact sheet of rest pose against posed, for judging a pose change by eye.

A pose is judged against what it replaced, never on its own: "does this look
like a creature standing" is a question a single picture cannot answer, because
the rest pose already looks like a creature — a stiff one, with its feet
pointing at the floor. So every asset here is drawn twice, the cache's rest pose
on the left and whatever `AssetCatalog.assemble()` chooses on the right, at the
same size, from the same views.

This exists because numbers lie here. A legs-only score once picked frames that
stood perfectly upright with both arms in the air, passed every threshold it was
measured against, and was only caught by looking at a sheet like this one.

Output goes to a tracked path (`images/pose_review/`) on purpose: a pose change
should leave a picture behind that somebody else can disagree with, rather than
a claim that it looked fine.

Examples:
    # the standing probe set - one creature per pose layer, plus the awkward ones
    python tools/pose_sheet.py --probe --tag before

    # a specific rig you are working on
    python tools/pose_sheet.py --skeletons 70 --per-skeleton 4 --tag griffon

    # named assets
    python tools/pose_sheet.py --ids 12009,13465,2000 --tag spot-check
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image, ImageDraw, ImageFont

from assets.asset_catalog import AssetCatalog, AssetKind
from assets.asset_manager import AssetManager
from tools.pose_render import DEFAULT_VIEWS, VIEWS, rasterise, slugify, triangles_of

# One creature per pose layer, plus the rigs whose stance is known to be wrong
# or known to be hard. Regenerated whenever a pose rule changes, so a regression
# somewhere the change was not aimed at cannot pass unlooked-at.
#
# The four rigs whose layer reads `+wingfold` are here for a stronger reason
# than the rest: their wing rotations are *written by this exporter* rather than
# read out of a clip (see `WING_FOLD_SKELETONS`), so they are the one place a
# picture is the only evidence there is.
PROBE_ASSETS: Sequence[int] = (
    2000,    # Aelfborn        skel 1   upright  - a plain biped, the easy case
    12000,   # Flesh Golem     skel 104 upright  - braced knees
    12009,   # Hunting Hound   skel 10  grounded - a plain quadruped
    13368,   # Viper           skel 82  grounded - no legs at all
    2004,    # Centaur         skel 47  grounded - two body plans at once
    13465,   # Hunting Griffon skel 70  grounded - wings, authored fold
    2002,    # Aracoix         skel 18  upright  - wings, authored fold
    2003,    # Aracoix         skel 20  upright  - wings, authored fold
    14078,   # Nelchael        skel 117 upright  - wings, authored fold
    13487,   # Lesser Wyvern   skel 88  grounded - wings, and only wings for arms
    12099,   # Bat             skel 55  grounded - wings on a rig that never lands
    12914,   # Rat-Man         skel 21  grounded - forelimbs up in every frame it has
    12021,   # Grobones        skel 8   rest     - biped, best leg tilt 46 degrees
    12022,   # Wight           skel 98  rest     - biped, best 37 degrees
    12152,   # Cave Troll      skel 13  rest     - biped, best 61 degrees
    2017,    # Minotaur        skel 54  rest     - the largest rest-pose rig
    12007,   # Air Elemental   skel 100 rest     - not bipedal and still no pose
)

HEADER_HEIGHT = 30
COLUMN_HEIGHT = 22
GUTTER = 14
BACKGROUND = (18, 19, 22)
DIVIDER = (70, 72, 82)


def load_font(size: int = 12):
    for candidate in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def creature_skeletons(catalog: AssetCatalog, am: AssetManager) -> Dict[int, List[int]]:
    """skeleton id -> the creature assets that use it."""
    by_skeleton: Dict[int, List[int]] = defaultdict(list)
    for asset_id in catalog.iter_asset_ids(AssetKind.CREATURE):
        cobj = am.load_cobject(asset_id)
        if cobj is None:
            continue
        _renders, skeleton_id = catalog._resolve_render_ids(asset_id, cobj)
        if skeleton_id is not None:
            by_skeleton[skeleton_id].append(asset_id)
    return by_skeleton


def pose_layer(am: AssetManager, skeleton_id: Optional[int]) -> str:
    """
    Which rung of `stand_pose` answered for this rig.

    Asked of the code that chose, never re-derived here: a sheet that ran the
    gates itself would keep labelling rows by an older ladder than the one the
    exporter uses, and the label would look right while being wrong.
    """
    if skeleton_id is None or am.load_skeleton(skeleton_id) is None:
        return "no-skeleton"
    return am.stand_layer(skeleton_id)


def _row(catalog: AssetCatalog, am: AssetManager, asset_id: int,
         views: Sequence[str], size: int, tint: bool, supersample: int
         ) -> Optional[Tuple[Sequence[str], List[Image.Image]]]:
    """Render one asset rest-then-posed, both to the same scale."""
    rest = catalog.assemble(asset_id, pose=False)
    posed = catalog.assemble(asset_id, pose=None)
    if rest is None or not rest.parts:
        return None

    rest_tris = triangles_of(rest, am, tint=tint)
    posed_tris = triangles_of(posed, am, tint=tint) if posed and posed.parts else rest_tris
    if not len(rest_tris):
        return None

    # One camera box across both, so a limb that moved reads as movement rather
    # than as the camera having zoomed. The rest pose is usually the taller of
    # the two, which is itself the thing being fixed.
    lo = np.minimum(rest_tris.bounds[0], posed_tris.bounds[0])
    hi = np.maximum(rest_tris.bounds[1], posed_tris.bounds[1])
    fit = (lo, hi)

    tiles = [rasterise(rest_tris, VIEWS[v], size, supersample=supersample, fit=fit)
             for v in views]
    tiles += [rasterise(posed_tris, VIEWS[v], size, supersample=supersample, fit=fit)
              for v in views]

    layer = pose_layer(am, rest.skeleton_id)
    # Compare the geometry, not the objects: a rig no clip stands returns {} and
    # is assembled at rest, so an identity check on the assembled asset would
    # report every rest-layer row as "posed" and hide exactly the rows that did
    # not move.
    moved = (posed_tris.positions.shape != rest_tris.positions.shape
             or not np.allclose(posed_tris.positions, rest_tris.positions))
    label = (
        f"{asset_id}  {rest.name}",
        f"skeleton {rest.skeleton_id} - {layer} - "
        f"{'posed' if moved else 'UNCHANGED'} - rest {hi[1] - lo[1]:.1f} tall",
    )
    return label, tiles


def build_sheet(rows: List[Tuple[Sequence[str], List[Image.Image]]],
                views: Sequence[str], size: int, path: Path) -> None:
    """Stack rendered rows into one labelled image: rest on the left, posed on the right."""
    font = load_font(12)
    small = load_font(11)
    per_side = len(views)
    width = per_side * 2 * size + GUTTER * 3
    row_height = HEADER_HEIGHT + size
    height = COLUMN_HEIGHT + len(rows) * row_height + GUTTER

    sheet = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(sheet)

    left_x = GUTTER
    right_x = GUTTER * 2 + per_side * size
    draw.text((left_x, 4), "REST POSE  (" + ", ".join(views) + ")",
              fill=(150, 150, 158), font=small)
    draw.text((right_x, 4), "POSED  (" + ", ".join(views) + ")",
              fill=(150, 200, 240), font=small)

    for i, (label, tiles) in enumerate(rows):
        top = COLUMN_HEIGHT + i * row_height
        draw.text((left_x, top + 2), label[0], fill=(225, 225, 230), font=font)
        draw.text((left_x, top + 15), label[1], fill=(140, 142, 152), font=small)
        for j, tile in enumerate(tiles):
            x = (left_x if j < per_side else right_x) + (j % per_side) * size
            sheet.paste(tile, (x, top + HEADER_HEIGHT))
        # The divider is the whole point of the layout: everything left of it is
        # what the change has to beat.
        draw.line([(right_x - GUTTER // 2, top + HEADER_HEIGHT),
                   (right_x - GUTTER // 2, top + row_height)], fill=DIVIDER, width=1)

    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    print(f"sheet|path={path}|rows={len(rows)}|{sheet.width}x{sheet.height}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", default=str(REPO_ROOT / "arcane_dump"))
    ap.add_argument("--out", default=str(REPO_ROOT / "images" / "pose_review"),
                    help="tracked by default, so a run leaves evidence behind")
    ap.add_argument("--tag", default="sheet", help="filename stem for this run")
    ap.add_argument("--ids", help="comma-separated asset IDs")
    ap.add_argument("--skeletons", help="comma-separated skeleton IDs")
    ap.add_argument("--per-skeleton", type=int, default=1,
                    help="assets to draw per skeleton when --skeletons is used")
    ap.add_argument("--probe", action="store_true",
                    help="the standing probe set: one creature per pose layer, plus the awkward rigs")
    ap.add_argument("--layer", action="append",
                    help="every skeleton on this pose layer (upright/grounded/rest), repeatable")
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--views", default=",".join(DEFAULT_VIEWS))
    ap.add_argument("--supersample", type=int, default=2)
    ap.add_argument("--no-tint", action="store_true")
    ap.add_argument("--rows-per-sheet", type=int, default=12)
    args = ap.parse_args()

    if not (args.ids or args.skeletons or args.probe or args.layer):
        ap.error("choose a selection: --probe, --ids, --skeletons, or --layer")

    views = [v.strip() for v in args.views.split(",") if v.strip()]
    unknown = [v for v in views if v not in VIEWS]
    if unknown:
        ap.error(f"unknown view(s) {unknown}; have {sorted(VIEWS)}")

    am = AssetManager(args.dump)
    catalog = AssetCatalog(am)

    wanted: List[int] = []
    if args.probe:
        wanted.extend(PROBE_ASSETS)
    if args.ids:
        wanted.extend(int(x) for x in args.ids.split(",") if x.strip())
    if args.skeletons or args.layer:
        by_skeleton = creature_skeletons(catalog, am)
        if args.skeletons:
            for raw in args.skeletons.split(","):
                if raw.strip():
                    wanted.extend(by_skeleton.get(int(raw), [])[: args.per_skeleton])
        if args.layer:
            asked = {v.strip().lower() for v in args.layer}
            for skeleton_id, assets in sorted(by_skeleton.items()):
                layer = pose_layer(am, skeleton_id)
                if any(layer.startswith(a) for a in asked):
                    wanted.extend(assets[: args.per_skeleton])

    seen: set = set()
    ordered = [a for a in wanted if not (a in seen or seen.add(a))]

    started = time.time()
    rows: List[Tuple[Sequence[str], List[Image.Image]]] = []
    for asset_id in ordered:
        row = _row(catalog, am, asset_id, views, args.size, not args.no_tint,
                   args.supersample)
        if row is None:
            print(f"no geometry|id={asset_id}")
            continue
        rows.append(row)
        print(f"  drew|id={asset_id}|{row[0][0]}|{row[0][1]}")

    if not rows:
        print("nothing to draw", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    pages = max(1, args.rows_per_sheet)
    for page_start in range(0, len(rows), pages):
        page = rows[page_start:page_start + pages]
        suffix = "" if len(rows) <= pages else f"_{page_start // pages}"
        build_sheet(page, views, args.size,
                    out_dir / f"{slugify(args.tag)}{suffix}.png")

    print(f"\nassets={len(rows)}|elapsed={time.time() - started:.1f}s|out={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
