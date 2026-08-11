#!/usr/bin/env python3
"""
Export every zone heightmap, with the transform that makes it terrain.

Why this exists
---------------
`terrain/` already holds the 20,912 blend masks -- how the ground textures mix. This is the
other half: the **elevation** of the ground they mix across.

The README used to say "all 14 continent heightmaps resolve in Textures.cache -- checked,
present, not yet extracted". That undercounted it. **178 zones name a heightmap and all 178
resolve**, from a 128x128 for Uthgaard up to 1024x384 for the Khar Thale Islands.

An image on its own is a picture, not terrain. What makes it terrain is in the zone's
`terrain_gen` record next to it, and nothing had read that either:

    terrain_image            the texture id
    terrain_x_size/z_size    the world footprint the image is stretched over
    terrain_min_y/max_y      the elevation the greyscale ramp spans
    terrain_height           the flat height for a PLANAR zone (no image)

So a sample maps to world height as

    y = min_y + (grey / 255) * (max_y - min_y)

and to a world position as `x_size / width` units per pixel. `min_y`/`max_y` read 0 and 800
on all 178, so the greyscale ramp is 0..800 world units -- **0 to 292 m** at the 2.7411
units/m in `reference/`, which is this world's ceiling on terrain elevation.

Two things are reported rather than smoothed over:

  * **Non-square sampling.** Units-per-pixel comes out clean (64, 100, 128, 192) on every
    zone but two: `Tyrranth Major` and `Macrozone Test Continent` are both 450x360 over a
    65536x49152 footprint, which is 145.6 across and 136.5 down. Flagged per zone as
    `squarePixels: false` rather than averaged into one number that is wrong both ways.
  * **Format.** 42 of the 43 distinct images decode with `len(image_data) == width *
    height`, one byte per sample. The 43rd, `1004000` (Kharduun and the Plain of Ashes), is
    24-bit -- but still a height field: sampled across the image its channels are equal on
    639 of 784 pixels and never differ by more than 1, which is lossy compression on
    something authored greyscale. Its red channel is taken and `maxChannelDelta` records
    the loss. Anything that is neither is listed under `problems` rather than written out
    as a plausible-looking wrong image; nothing currently lands there.

178 zones share 43 images -- the small zones reuse a handful of terrains between them, so
this is 6.6 MB rather than the 40 MB a per-zone copy would cost.

Do not upscale these. Two of them (`1005400`, `1005813`) are already sitting in
`textures_2x/` as Lanczos upscales, which is the right treatment for art and the wrong one
for a height field -- it invents elevations between samples and softens coastlines.

Usage:
    python tools/export_terrain.py --out export_aegisfall/maps/terrain
    python tools/export_terrain.py --sample 6          # a few, to look at first
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image

from arcane.util.ResStream import ResStream
from arcane.zones.ArcZone import ArcZone
from assets.asset_manager import AssetManager
from assets.cache_archive import CacheArchive

# From reference/summary.json. Stated here so the metre column is reproducible rather than
# depending on that file having been generated.
UNITS_PER_METRE = 2.7411


def zone_terrain(dump: Path) -> List[Dict[str, Any]]:
    """Every zone with a terrain generator, image-backed or flat."""
    path = next(iter(sorted(dump.rglob("CZone.cache"))), None)
    if path is None:
        raise SystemExit("CZone.cache not found beneath " + str(dump))
    archive = CacheArchive(path)
    rows: List[Dict[str, Any]] = []
    for zone_id in archive.ids():
        try:
            zone = ArcZone()
            zone.load_binary(ResStream(archive.read(zone_id)))
            record = zone.save_json()
        except Exception:  # noqa: BLE001
            continue
        gen = record.get("zone_terrain_gen")
        if not isinstance(gen, dict):
            continue
        rows.append({
            "zoneId": zone_id,
            "name": record.get("zone_name"),
            "majorRadius": record.get("zone_major_radius"),
            "minorRadius": record.get("zone_minor_radius"),
            "terrainType": gen.get("terrain_type"),
            "image": gen.get("terrain_image") or None,
            "minY": gen.get("terrain_min_y"),
            "maxY": gen.get("terrain_max_y"),
            "xSize": gen.get("terrain_x_size"),
            "zSize": gen.get("terrain_z_size"),
            "flatHeight": gen.get("terrain_height"),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", default=str(REPO_ROOT / "arcane_dump"))
    ap.add_argument("--out",
                    default=str(REPO_ROOT / "export_aegisfall" / "maps" / "terrain"))
    ap.add_argument("--sample", type=int, default=0,
                    help="write only the N largest zones, for a look before the full run")
    args = ap.parse_args()
    started = time.time()

    dump, out = Path(args.dump), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manager = AssetManager(str(dump))

    rows = zone_terrain(dump)
    imaged = [r for r in rows if r["image"]]
    flat = [r for r in rows if not r["image"]]
    imaged.sort(key=lambda r: -(r["majorRadius"] or 0))
    wanted = imaged[:args.sample] if args.sample else imaged

    written: List[Dict[str, Any]] = []
    problems: List[Dict[str, Any]] = []
    seen_images: Dict[int, str] = {}

    for row in wanted:
        texture_id = row["image"]
        texture = manager.load_texture(texture_id)
        if texture is None:
            problems.append({"zone": row["zoneId"], "image": texture_id,
                             "issue": "not in Textures.cache"})
            continue
        width = int(texture.image_width or 0)
        height = int(texture.image_height or 0)
        data = texture.image_data or b""
        source = None
        image = None
        if width > 0 and height > 0 and len(data) == width * height:
            source = "8-bit"
            image = Image.frombytes("L", (width, height), data)
            channel_delta = 0
        else:
            # `1004000`, shared by Kharduun and the Plain of Ashes, is 24-bit rather than
            # 8-bit. It is still a height field: sampled across the image the channels are
            # equal on 639 of 784 pixels and never differ by more than 1, which is lossy
            # compression on something authored greyscale. The red channel is taken rather
            # than a luma conversion, because weighting three copies of one number by 601
            # coefficients is a way to get a different number for no reason. The largest
            # channel disagreement is reported so the loss is visible.
            decoded = None
            try:
                decoded = manager.load_texture_image(texture_id)
            except Exception:  # noqa: BLE001
                decoded = None
            if decoded is None or decoded.mode not in ("RGB", "RGBA", "L"):
                problems.append({"zone": row["zoneId"], "image": texture_id,
                                 "issue": "payload is neither 8-bit nor a decodable image",
                                 "width": width, "height": height, "bytes": len(data)})
                continue
            if decoded.mode == "L":
                source, channel_delta, image = "8-bit", 0, decoded
            else:
                bands = decoded.split()[:3]
                channel_delta = max(
                    max(abs(a - b) for a, b in zip(bands[i].tobytes(),
                                                   bands[j].tobytes()))
                    for i, j in ((0, 1), (1, 2)))
                source, image = "24-bit, red channel", bands[0]
            width, height = decoded.size

        name = str(texture_id) + ".png"
        if texture_id not in seen_images:
            image.save(out / name)
            seen_images[texture_id] = name

        span = (row["maxY"] or 0) - (row["minY"] or 0)
        across = (row["xSize"] or 0) / width
        down = (row["zSize"] or 0) / height
        written.append({
            **row,
            "file": name,
            "width": width,
            "height": height,
            "unitsPerPixelX": round(across, 4),
            "unitsPerPixelZ": round(down, 4),
            "squarePixels": abs(across - down) < 1e-6,
            "source": source,
            **({"maxChannelDelta": channel_delta} if channel_delta else {}),
            "heightSpanUnits": span,
            "heightSpanMetres": round(span / UNITS_PER_METRE, 2),
            "sampleToHeight": "y = minY + (grey / 255) * (maxY - minY)",
        })

    payload = {
        "generator": "tools/export_terrain.py",
        "note": ("One 8-bit greyscale PNG per zone heightmap, plus the transform that "
                 "places it: `unitsPerPixelX/Z` across the ground and `sampleToHeight` up. "
                 "`squarePixels` false means the image is stretched unevenly and the two "
                 "unitsPerPixel figures differ. Zones with terrainType PLANAR carry no "
                 "image and sit at `flatHeight`. `source` says whether the record was "
                 "8-bit or a 24-bit texture the red channel was taken from. Do not upscale "
                 "these -- it invents elevations between samples."),
        "unitsPerMetre": UNITS_PER_METRE,
        "counts": {
            "zonesWithTerrainGen": len(rows),
            "zonesWithHeightmap": len(imaged),
            "zonesFlat": len(flat),
            "written": len(written),
            "distinctImages": len(seen_images),
        },
        "problems": problems,
        "flat": flat,
        "zones": written,
    }
    (out / "terrain.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")

    stretched = [r["zoneId"] for r in written if not r["squarePixels"]]
    total = sum((out / n).stat().st_size for n in seen_images.values())
    print("zones with a terrain generator " + str(len(rows))
          + "  heightmapped " + str(len(imaged)) + "  flat " + str(len(flat)))
    print("  wrote " + str(len(seen_images)) + " PNGs for " + str(len(written))
          + " zones, %.1f MB" % (total / 1048576))
    if stretched:
        print("  non-square pixels on " + str(len(stretched)) + " zones: " + str(stretched))
    if problems:
        print("  " + str(len(problems)) + " zones skipped: "
              + "; ".join(str(p["zone"]) + " " + p["issue"] for p in problems[:4]))
    else:
        print("  every heightmap resolved and decoded")
    print("wrote " + str(out) + "  in %.1fs" % (time.time() - started))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
