#!/usr/bin/env python3
"""
Render an assembled asset offscreen, with no GPU, browser or display.

`render_thumbnails.py` draws through the viewer's GL path, which needs a Qt
application and a window. That is the wrong instrument for judging a *pose*:
posing work has to be checkable from a script, in CI, on a headless box, and
against a change that has not been exported yet.

So this is a plain numpy z-buffer rasteriser over whatever
`AssetCatalog.assemble()` produces. It drives the real assembler rather than
reimplementing it — a second assembler would be a second answer to the question
the exporter already answers, and the two would drift.

What it is for, and what it is not. It shows **silhouette and limb placement**:
arms in the air, wings splayed, a sprawled body, a limb buried in a torso, a
figure floating off its own root. It is flat-shaded and untextured, so it says
nothing about materials, UVs or smoothing. That is deliberate — a pose defect is
a shape defect, and texture only makes one harder to see.

Two conventions, stated rather than assumed, both from `guard_angles.py`: the
legacy skeleton is **+Y up** and **+Z forward**. So the side view puts the
creature's forward at screen right, and the front view looks it in the face. A
faint line marks the y=0 plane the skeleton root sits on, which is what makes
"floating" and "sunk" visible at a glance.

Parts are tinted by which limb their bone belongs to, and the left side is drawn
darker than the right. Both are diagnostics rather than decoration: an arm in the
air and a leg in the air look identical in flat grey, and a mirroring fault is
invisible without a side cue. `--no-tint` turns it off.

Examples:
    # one creature, both views, its automatic stand pose
    python tools/pose_render.py --ids 12000 --out /tmp/shots

    # the same creature as the cache stores it, for comparison
    python tools/pose_render.py --ids 12000 --rest-pose --out /tmp/shots

    # a named clip frame, to judge a candidate before adopting it
    python tools/pose_render.py --ids 13060 --pose 1000042:12 --out /tmp/shots
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image

from assets.asset_catalog import AssetCatalog, AssembledAsset
from assets.asset_manager import AssetManager

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def slugify(name: str) -> str:
    return _UNSAFE.sub("_", (name or "").strip()).strip("_") or "unnamed"


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class View:
    """
    An orthographic camera as three world-space axes.

    `right` and `up` are the screen axes; `toward` points at the camera, so a
    larger dot product means nearer and the depth test keeps the maximum.

    Orthographic on purpose: perspective foreshortens exactly the limb that is
    pointing at the camera, which is the one a pose check most needs to measure.
    """

    name: str
    right: Tuple[float, float, float]
    up: Tuple[float, float, float]
    toward: Tuple[float, float, float]


# +Y up, +Z forward. Side view faces the creature's forward to screen right.
VIEWS: Dict[str, View] = {
    "side": View("side", (0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)),
    "front": View("front", (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "top": View("top", (1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
}
DEFAULT_VIEWS = ("side", "front")

# Key light: above, to the left, in front. Chosen so a limb held out to the side
# separates from the torso behind it instead of merging into one flat mass.
LIGHT = (-0.40, 0.65, 0.75)
AMBIENT = 0.34
BACKGROUND = (26, 27, 31)
GROUND_LINE = (58, 60, 68)

# Bone name -> limb class. Ordered: the first match wins, so a forelimb's RADIUS
# is claimed by the arm rule before the leg rule can see its CLAW.
LIMB_CLASSES: Sequence[Tuple[str, Tuple[str, ...], Tuple[int, int, int]]] = (
    ("wing", ("WING", "PINION", "FEATHER"), (140, 205, 150)),
    ("tail", ("TAIL",), (192, 150, 212)),
    ("head", ("HEAD", "NECK", "SKULL", "JAW", "HORN", "HAIR", "BEARD", "HELM",
              "EAR", "EYE", "MANE", "SNOUT", "MUZZLE"), (228, 206, 132)),
    ("arm", ("HUMERUS", "RADIUS", "ULNA", "FOREARM", "HAND", "FINGER", "THUMB",
             "CLAVICLE", "SHOULDER", "WRIST"), (218, 150, 118)),
    ("leg", ("FEMUR", "TIBIA", "FIBULA", "FOOT", "TOE", "HOOF", "PAW", "CLAW",
             "THIGH", "SHIN", "ANKLE", "HIP", "LEG"), (118, 162, 218)),
)
BODY_COLOUR = (186, 186, 192)
# The stored side is drawn full strength and its mirrored twin darker, so a part
# landing on the wrong joint reads as an asymmetry rather than as nothing.
LEFT_DIM = 0.78


def limb_colour(bone: Optional[str], tint: bool = True) -> Tuple[int, int, int]:
    if not tint:
        return BODY_COLOUR
    name = (bone or "").upper()
    colour = BODY_COLOUR
    for _label, keys, rgb in LIMB_CLASSES:
        if any(k in name for k in keys):
            colour = rgb
            break
    if name.startswith("L"):
        colour = tuple(int(c * LEFT_DIM) for c in colour)
    return colour


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
@dataclass
class Triangles:
    """World-space triangle soup, with one flat colour per face."""

    positions: np.ndarray   # (n, 3, 3)
    colours: np.ndarray     # (n, 3) uint8

    def __len__(self) -> int:
        return len(self.positions)

    @property
    def bounds(self) -> Tuple[np.ndarray, np.ndarray]:
        flat = self.positions.reshape(-1, 3)
        return flat.min(axis=0), flat.max(axis=0)


def triangles_of(asset: AssembledAsset, am: AssetManager, tint: bool = True) -> Triangles:
    """
    Flatten an assembled asset into world-space triangles.

    Index and face filtering match `export_assets.py`: a mesh whose indices
    overrun its vertex list is real in this cache, and a face referencing a
    vertex that is not there would otherwise raise inside the rasteriser.
    """
    chunks: List[np.ndarray] = []
    colours: List[np.ndarray] = []

    for part in asset.parts:
        mesh = am.load_mesh(part.mesh_id)
        if mesh is None or not getattr(mesh, "mesh_vertices", None):
            continue
        vertices = np.asarray(mesh.mesh_vertices, dtype=np.float64)
        indices = np.asarray(getattr(mesh, "mesh_indices", None) or [], dtype=np.int64)
        if indices.size < 3 or vertices.size == 0:
            continue
        faces = indices[: (indices.size // 3) * 3].reshape(-1, 3)
        faces = faces[(faces >= 0).all(axis=1) & (faces < len(vertices)).all(axis=1)]
        if not len(faces):
            continue

        xform = np.asarray(part.transform, dtype=np.float64)
        world = vertices @ xform[:3, :3].T + xform[:3, 3]
        tris = world[faces]                                  # (f, 3, 3)
        chunks.append(tris)
        rgb = np.asarray(limb_colour(part.target_bone, tint), dtype=np.uint8)
        colours.append(np.repeat(rgb[None, :], len(tris), axis=0))

    if not chunks:
        return Triangles(np.zeros((0, 3, 3)), np.zeros((0, 3), dtype=np.uint8))
    return Triangles(np.concatenate(chunks), np.concatenate(colours))


# ---------------------------------------------------------------------------
# Rasteriser
# ---------------------------------------------------------------------------
def _shade(tris: Triangles) -> np.ndarray:
    """
    Flat lambert per face, lit from both sides.

    Two-sided on purpose: winding is not consistent across this cache, so a
    one-sided term draws whole limbs black and that reads as missing geometry —
    the one failure a pose check must not invent.
    """
    edge1 = tris.positions[:, 1] - tris.positions[:, 0]
    edge2 = tris.positions[:, 2] - tris.positions[:, 0]
    normals = np.cross(edge1, edge2)
    lengths = np.linalg.norm(normals, axis=1)
    safe = np.maximum(lengths, 1e-12)
    normals = normals / safe[:, None]

    light = np.asarray(LIGHT, dtype=np.float64)
    light = light / np.linalg.norm(light)
    lambert = np.abs(normals @ light)
    intensity = AMBIENT + (1.0 - AMBIENT) * lambert
    shaded = tris.colours.astype(np.float64) * intensity[:, None]
    # Degenerate faces carry no normal; drawing them unlit is better than NaN.
    shaded[lengths <= 1e-12] = tris.colours[lengths <= 1e-12] * AMBIENT
    return np.clip(shaded, 0, 255)


def rasterise(tris: Triangles, view: View, size: int, *,
              supersample: int = 2, margin: float = 0.08,
              fit: Optional[Tuple[np.ndarray, np.ndarray]] = None) -> Image.Image:
    """
    Draw triangles into an image with a z-buffer, in pure numpy.

    `fit` overrides the bounding box the camera frames, so a pair of images can
    be drawn to one scale. Left unset, each image frames its own subject, which
    is what makes a rest pose and a stand pose equally legible side by side even
    though one is half again as tall.
    """
    scale_px = max(1, supersample)
    width = height = size * scale_px
    image = np.zeros((height, width, 3), dtype=np.float64)
    image[:, :] = BACKGROUND
    depth = np.full((height, width), -np.inf, dtype=np.float64)

    if len(tris) == 0:
        return Image.fromarray(image.astype(np.uint8)).resize(
            (size, size), Image.Resampling.LANCZOS)

    right = np.asarray(view.right, dtype=np.float64)
    up = np.asarray(view.up, dtype=np.float64)
    toward = np.asarray(view.toward, dtype=np.float64)

    lo, hi = fit if fit is not None else tris.bounds
    corners = np.array([[x, y, z] for x in (lo[0], hi[0])
                        for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    us, vs = corners @ right, corners @ up
    centre_u, centre_v = (us.min() + us.max()) / 2.0, (vs.min() + vs.max()) / 2.0
    extent = max(us.max() - us.min(), vs.max() - vs.min(), 1e-6)
    scale = (width * (1.0 - margin * 2.0)) / extent

    def to_screen(points: np.ndarray) -> np.ndarray:
        px = (points @ right - centre_u) * scale + width / 2.0
        py = height / 2.0 - (points @ up - centre_v) * scale
        pz = points @ toward
        return np.stack([px, py, pz], axis=-1)

    # The y=0 plane the skeleton root stands on. Drawn under the model so a
    # limb crossing it stays visible.
    ground_v = height / 2.0 + centre_v * scale
    row = int(round(ground_v))
    if 0 <= row < height:
        image[row, :] = GROUND_LINE

    screen = to_screen(tris.positions.reshape(-1, 3)).reshape(-1, 3, 3)
    shaded = _shade(tris)

    xs, ys, zs = screen[..., 0], screen[..., 1], screen[..., 2]
    min_x = np.clip(np.floor(xs.min(axis=1)).astype(int), 0, width - 1)
    max_x = np.clip(np.ceil(xs.max(axis=1)).astype(int), 0, width - 1)
    min_y = np.clip(np.floor(ys.min(axis=1)).astype(int), 0, height - 1)
    max_y = np.clip(np.ceil(ys.max(axis=1)).astype(int), 0, height - 1)
    # Wholly offscreen faces have a clamped box that is still one pixel wide, so
    # cull on the unclamped extent instead.
    onscreen = ((xs.max(axis=1) >= 0) & (xs.min(axis=1) < width) &
                (ys.max(axis=1) >= 0) & (ys.min(axis=1) < height))

    area = ((xs[:, 1] - xs[:, 0]) * (ys[:, 2] - ys[:, 0]) -
            (xs[:, 2] - xs[:, 0]) * (ys[:, 1] - ys[:, 0]))

    for i in np.nonzero(onscreen & (np.abs(area) > 1e-9))[0]:
        x0, x1, x2 = xs[i]
        y0, y1, y2 = ys[i]
        z0, z1, z2 = zs[i]
        gx = np.arange(min_x[i], max_x[i] + 1) + 0.5
        gy = np.arange(min_y[i], max_y[i] + 1) + 0.5
        if gx.size == 0 or gy.size == 0:
            continue
        px = gx[None, :]
        py = gy[:, None]

        inv = 1.0 / area[i]
        # Dividing by the *signed* area makes the barycentrics positive inside
        # the triangle whichever way it is wound, so no winding fix is needed.
        l0 = ((x1 - px) * (y2 - py) - (x2 - px) * (y1 - py)) * inv
        l1 = ((x2 - px) * (y0 - py) - (x0 - px) * (y2 - py)) * inv
        l2 = 1.0 - l0 - l1
        inside = (l0 >= 0.0) & (l1 >= 0.0) & (l2 >= 0.0)
        if not inside.any():
            continue

        z = l0 * z0 + l1 * z1 + l2 * z2
        window = depth[min_y[i]:max_y[i] + 1, min_x[i]:max_x[i] + 1]
        nearer = inside & (z > window)
        if not nearer.any():
            continue
        window[nearer] = z[nearer]
        image[min_y[i]:max_y[i] + 1, min_x[i]:max_x[i] + 1][nearer] = shaded[i]

    out = Image.fromarray(image.astype(np.uint8))
    if scale_px > 1:
        out = out.resize((size, size), Image.Resampling.LANCZOS)
    return out


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------
def render_asset(catalog: AssetCatalog, am: AssetManager, asset_id: int, *,
                 pose=None, views: Iterable[str] = DEFAULT_VIEWS, size: int = 256,
                 tint: bool = True, supersample: int = 2,
                 fit: Optional[Tuple[np.ndarray, np.ndarray]] = None
                 ) -> Tuple[Optional[AssembledAsset], Dict[str, Image.Image], Optional[Triangles]]:
    """Assemble one asset and draw it from each named view."""
    asset = catalog.assemble(asset_id, pose=pose)
    if asset is None or not asset.parts:
        return asset, {}, None
    tris = triangles_of(asset, am, tint=tint)
    images = {
        name: rasterise(tris, VIEWS[name], size, supersample=supersample, fit=fit)
        for name in views
    }
    return asset, images, tris


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", default=str(REPO_ROOT / "arcane_dump"))
    ap.add_argument("--out", default=str(REPO_ROOT / "images" / "pose_review" / "shots"))
    ap.add_argument("--ids", required=True, help="comma-separated asset IDs")
    ap.add_argument("--size", type=int, default=384)
    ap.add_argument("--views", default=",".join(DEFAULT_VIEWS),
                    help=f"comma-separated, from {sorted(VIEWS)}")
    ap.add_argument("--supersample", type=int, default=2)
    ap.add_argument("--no-tint", action="store_true", help="one flat grey for every part")
    ap.add_argument("--pose", help="stand on a specific clip frame: MOTION_ID[:FRAME]")
    ap.add_argument("--rest-pose", action="store_true",
                    help="draw the cache's rest pose, skipping the automatic stand")
    args = ap.parse_args()

    if args.pose and args.rest_pose:
        ap.error("--pose and --rest-pose ask for opposite things")

    views = [v.strip() for v in args.views.split(",") if v.strip()]
    unknown = [v for v in views if v not in VIEWS]
    if unknown:
        ap.error(f"unknown view(s) {unknown}; have {sorted(VIEWS)}")

    am = AssetManager(args.dump)
    catalog = AssetCatalog(am)

    pose = False if args.rest_pose else None
    if args.pose:
        motion_id, _, frame = args.pose.partition(":")
        try:
            pose = am.load_motion_pose(int(motion_id), int(frame or 0))
        except ValueError:
            ap.error(f"--pose wants MOTION_ID[:FRAME], got {args.pose!r}")
        if not pose:
            ap.error(f"motion {motion_id} has no frame data to pose from")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = "rest" if args.rest_pose else ("clip" if args.pose else "stand")

    for asset_id in (int(x) for x in args.ids.split(",") if x.strip()):
        asset, images, tris = render_asset(
            catalog, am, asset_id, pose=pose, views=views, size=args.size,
            tint=not args.no_tint, supersample=args.supersample)
        if not images:
            print(f"no geometry|id={asset_id}")
            continue
        lo, hi = tris.bounds
        for name, image in images.items():
            path = out_dir / f"{asset_id}_{slugify(asset.name)}_{tag}_{name}.png"
            image.save(path)
            print(f"drew|id={asset_id}|view={name}|tris={len(tris)}"
                  f"|extent={hi[0] - lo[0]:.1f}x{hi[1] - lo[1]:.1f}x{hi[2] - lo[2]:.1f}"
                  f"|skeleton={asset.skeleton_id}|path={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
