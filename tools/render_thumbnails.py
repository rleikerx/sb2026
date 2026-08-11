#!/usr/bin/env python3
"""
Render every asset to a thumbnail and tile them into browsable contact sheets.

9,900 GLB files are not a reference you can look at. This renders each asset
through the viewer's own GL path, then lays the results out per category with
ID and name under each tile, so a thousand buildings can be scanned on a few
pages instead of opened one at a time.

Outputs:
    thumbs/<Kind>/<id>_<name>.png   individual renders
    sheets/<Kind>_<n>.png           labelled contact sheets
    thumbs.json                     id -> file, for building other views

Usage:
    python tools/render_thumbnails.py --sample 24 --out export_aegisfall/reference
    python tools/render_thumbnails.py --all --size 256 --out export_aegisfall/reference
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image, ImageDraw, ImageFont
from PyQt6.QtWidgets import QApplication

from assets.asset_manager import AssetManager
from assets.asset_catalog import AssetCatalog
from ui.opengl_viewport import OpenGLViewport

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
LABEL_HEIGHT = 26


def slugify(name: str) -> str:
    return _UNSAFE.sub("_", (name or "").strip()).strip("_") or "unnamed"


def load_font(size: int = 11):
    for candidate in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def build_sheets(tiles: List[tuple], out_dir: Path, kind: str,
                 columns: int, tile: int, per_sheet: int) -> List[str]:
    """Tile (label, image) pairs into labelled contact sheets."""
    font = load_font()
    cell_h = tile + LABEL_HEIGHT
    written: List[str] = []

    for page_start in range(0, len(tiles), per_sheet):
        page = tiles[page_start:page_start + per_sheet]
        rows = (len(page) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * tile, rows * cell_h), (24, 24, 26))
        draw = ImageDraw.Draw(sheet)

        for i, (label, img) in enumerate(page):
            x = (i % columns) * tile
            y = (i // columns) * cell_h
            sheet.paste(img, (x, y))
            # Two short lines: ID above name, clipped rather than wrapped.
            for line_no, text in enumerate(label):
                if len(text) > 24:
                    text = text[:23] + "…"
                draw.text((x + 3, y + tile + 1 + line_no * 12), text,
                          fill=(210, 210, 210) if line_no else (130, 170, 220), font=font)

        page_no = page_start // per_sheet
        path = out_dir / f"{kind}_{page_no}.png"
        sheet.save(path)
        written.append(path.name)
        print(f"  sheet|{path.name}|tiles={len(page)}|{sheet.width}x{sheet.height}")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", default=str(REPO_ROOT / "arcane_dump"))
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "reference"))
    ap.add_argument("--size", type=int, default=256, help="thumbnail edge in px")
    ap.add_argument("--columns", type=int, default=8)
    ap.add_argument("--per-sheet", type=int, default=64)
    ap.add_argument("--kind", action="append")
    ap.add_argument("--sample", type=int, help="only N per category (test run)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--flush-every", type=int, default=150,
                    help="release GPU buffers every N assets")
    args = ap.parse_args()

    if not (args.sample or args.all or args.kind):
        ap.error("choose a selection: --sample N, --kind, or --all")

    app = QApplication(sys.argv[:1])
    am = AssetManager(args.dump)
    catalog = AssetCatalog(am)

    out_dir = Path(args.out)
    thumb_root = out_dir / "thumbs"
    sheet_root = out_dir / "sheets"
    thumb_root.mkdir(parents=True, exist_ok=True)
    sheet_root.mkdir(parents=True, exist_ok=True)

    viewport = OpenGLViewport(am)
    viewport.resize(args.size, args.size)
    viewport.show()
    app.processEvents()

    # The viewport drives itself at 60 FPS for animation playback. Left running,
    # every queued tick repaints the scene again and dominates a batch render.
    for timer_name in ("animation_timer", "fps_timer"):
        timer = getattr(viewport, timer_name, None)
        if timer is not None:
            timer.stop()

    kinds = catalog.list_kinds()
    if args.kind:
        requested = {k.lower() for k in args.kind}
        kinds = [k for k in kinds if k.value.lower() in requested]
        if not kinds:
            print(f"no matching category|given={args.kind}", file=sys.stderr)
            return 2

    index: Dict[str, dict] = {}
    started = time.time()
    total = 0

    for kind in kinds:
        tiles: List[tuple] = []
        folder = thumb_root / kind.value
        folder.mkdir(parents=True, exist_ok=True)
        rendered = 0

        for asset_id in catalog.iter_asset_ids(kind):
            asset = catalog.assemble(asset_id)
            if asset is None or not asset.parts:
                continue

            viewport.load_assembled_asset(asset)
            # grabFramebuffer renders the scene itself; an extra repaint() and
            # processEvents() round just pays for the same frame twice more.
            qimg = viewport.grabFramebuffer()
            path = folder / f"{asset_id}_{slugify(asset.name)}.png"
            qimg.save(str(path))

            tiles.append(((str(asset_id), asset.name), Image.open(path).convert("RGB")))
            index[str(asset_id)] = {
                "name": asset.name,
                "kind": kind.value,
                "file": f"thumbs/{kind.value}/{path.name}",
            }
            rendered += 1
            total += 1

            # Every asset uploads its meshes and textures to the GPU; without
            # periodic release a full run exhausts video memory.
            if rendered % args.flush_every == 0:
                viewport.makeCurrent()
                viewport.mesh_renderer.cleanup()
                viewport.texture_manager.cleanup()
                viewport.doneCurrent()
                # Drop only the heavy caches. Parsed cobjects and renders are
                # small and expensive to rebuild, so they stay.
                am.meshes.clear()
                am.textures.clear()
                am.texture_images.clear()
                print(f"  {kind.value}: {rendered} ({time.time() - started:.0f}s)")

            if args.sample and rendered >= args.sample:
                break

        if tiles:
            print(f"{kind.value}: rendered={rendered}")
            build_sheets(tiles, sheet_root, kind.value,
                         args.columns, args.size, args.per_sheet)

    with (out_dir / "thumbs.json").open("w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)

    print(f"\nthumbnails={total}|elapsed={time.time() - started:.1f}s|out={out_dir}")
    viewport.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
