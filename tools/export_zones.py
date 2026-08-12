#!/usr/bin/env python3
"""
Export the world: every zone in `CZone.cache` with the placement of everything in it.

`export_assets.py` answers "what does this building look like"; this answers
"where does that building stand". Each zone record carries its terrain settings
and two placement lists — props (buildings, walls, trees, furniture) and mobile
spawns — each with a world position, a Y rotation and the template ID of the
asset placed there. Those template IDs are the same IDs `export_assets.py`
writes files for, so a consumer joins the two on `asset_id` and has a world.

Writes three things:

    zones/index.json              one row per zone: name, type, radii, counts
    zones/placements/<id>.json    props + spawns for one zone, with positions
    zones/required_models.json    the distinct models the world places, with
                                  placement counts — i.e. exactly which files
                                  from `models/` a client needs to draw it

`required_models.json` is the point of the tool. Without it, "which of the 1,057
structures do we need" is a judgement call; with it, it is a lookup.

Two things this deliberately does not invent. Placements are in each zone's own
local space and the cache carries **no parent link**, so zones cannot be
assembled into one continuous map from this data alone — the continents are here
as zones with radii, but hold no props of their own. And `zoneType` is the
zone's *shape* (0 elliptical, 1 rectangular), not a level in a hierarchy; it is
passed through unmodified so nobody reads it as one.

Examples:
    python tools/export_zones.py --out export_aegisfall/zones
    python tools/export_zones.py --sample 5           # five zones, to eyeball
    python tools/export_zones.py --named-only         # skip the 643 unnamed
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arcane.zones.ArcZone import ArcZone
from assets.asset_catalog import AssetCatalog
from assets.asset_manager import AssetManager
from assets.cache_archive import CacheArchive

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def slugify(name: str) -> str:
    return _UNSAFE.sub("_", (name or "").strip()).strip("_") or "unnamed"


def find_czone(dump: Path) -> Path:
    """`CZone.cache` anywhere beneath the dump, matched by filename like the viewer does."""
    for path in sorted(dump.rglob("CZone.cache")):
        return path
    raise SystemExit(f"CZone.cache not found beneath {dump}")


class ZoneExporter:
    def __init__(self, catalog: Optional[AssetCatalog]):
        self.catalog = catalog
        self._name_cache: Dict[int, tuple] = {}
        # asset_id -> placement count, over every zone
        self.required: Counter = Counter()
        self.unresolved: Counter = Counter()

    def describe(self, asset_id: int) -> tuple:
        """(name, kind) for a template ID, or (None, None) when the catalogue has no such asset."""
        if asset_id in self._name_cache:
            return self._name_cache[asset_id]
        result = (None, None)
        if self.catalog is not None:
            try:
                name = self.catalog._get_name(asset_id)
                kind = self.catalog._get_kind(asset_id)
                if name:
                    result = (name, str(kind) if kind is not None else None)
            except Exception:
                result = (None, None)
        self._name_cache[asset_id] = result
        return result

    def placement(self, basic, template_id: int, *, counts: bool = True) -> dict:
        """
        One placed thing: where it is, which way it faces, and what it is.

        `counts` is false for mobiles, whose template ID is always 0 — counting those
        would put a phantom "Asset 0, 6,397 placements" at the top of the required list,
        which is the shape of error `required_models.json` exists to prevent.
        """
        x, y, z = basic.basic_zone_spawn_location
        name, kind = self.describe(template_id)
        if not counts:
            pass
        elif name is None:
            self.unresolved[template_id] += 1
        else:
            self.required[template_id] += 1
        row = {
            "assetId": template_id,
            "name": name,
            "kind": kind,
            "pos": [round(x, 4), round(y, 4), round(z, 4)],
            "yRot": round(basic.basic_zone_y_rot, 6),
        }
        # Only carried when the zone actually overrides it — most placements do not, and an
        # empty string per row is 47,000 empty strings.
        if basic.basic_zone_name_override:
            row["label"] = basic.basic_zone_name_override
        if basic.basic_zone_spawn_radius:
            row["radius"] = round(basic.basic_zone_spawn_radius, 4)
        return row

    def props(self, props, out: List[dict], depth: int = 0) -> None:
        """Props nest — a building holds its own furniture — so this recurses and records depth."""
        for prop in props:
            data = prop.prop_data
            row = self.placement(data.prop_basic_zone, data.prop_basic_zone.basic_zone_template_id)
            row["propType"] = prop.prop_type
            if depth:
                row["depth"] = depth
            if getattr(data, "prop_is_light_data", False):
                row["light"] = {
                    "color": data.prop_light_color,
                    "radius": round(data.prop_light_radius, 4),
                }
            if getattr(data, "prop_has_teleporter", False):
                row["teleporter"] = data.prop_teleporter
            out.append(row)
            self.props(data.prop_content_props, out, depth + 1)
            for mobile in data.prop_content_mobiles:
                out_row = self.mobile(mobile)
                out_row["insideProp"] = row["assetId"]
                self._spawns.append(out_row)

    def mobile(self, mobile) -> dict:
        """
        A spawn point.

        The creature is named by `mobile_rune_stone_ids`, not by the template ID — every
        mobile in the cache carries the same template, so the runes are the identity.
        """
        data = mobile.mobile_data
        basic = data.mobile_base_zone
        row = self.placement(basic, basic.basic_zone_template_id, counts=False)
        row["mobileType"] = mobile.mobile_type
        row["level"] = getattr(data, "mobile_level", None)
        row["count"] = getattr(data, "mobile_number_in_group", None)
        row["respawnS"] = round(basic.basic_zone_time_to_respawn, 3)
        runes = list(getattr(data, "mobile_rune_stone_ids", []) or [])
        if runes:
            row["runes"] = runes
            named = [self.describe(r)[0] for r in runes]
            row["runeNames"] = [n for n in named if n]
        return row

    def zone(self, zone_id: int, zone: ArcZone) -> dict:
        props: List[dict] = []
        self._spawns: List[dict] = []
        self.props(zone.zone_prop_info, props)
        for mobile in zone.zone_mobile_info:
            self._spawns.append(self.mobile(mobile))
        return {
            "zoneId": zone_id,
            "name": zone.zone_name,
            "zoneType": zone.zone_type,
            "peaceZone": zone.zone_peace_zone,
            "guildZone": zone.zone_guild_zone,
            "minorRadius": zone.zone_minor_radius,
            "majorRadius": zone.zone_major_radius,
            "yOffset": zone.zone_y_offset,
            "globalHeight": zone.zone_global_height,
            "seaLevel": zone.zone_sea_level,
            "hasWater": zone.zone_has_water,
            "props": props,
            "spawns": self._spawns,
        }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", default=str(REPO_ROOT / "arcane_dump"))
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "zones"))
    ap.add_argument("--sample", type=int, help="export N zones (test run)")
    ap.add_argument("--named-only", action="store_true",
                    help="skip zones with an empty name")
    ap.add_argument("--no-catalog", action="store_true",
                    help="skip name resolution (much faster; IDs only)")
    ap.add_argument("--models", default=str(REPO_ROOT / "export_aegisfall" / "models" / "assets.json"),
                    help="models/assets.json, to name the file each placement needs")
    args = ap.parse_args()

    dump = Path(args.dump)
    out = Path(args.out)
    (out / "placements").mkdir(parents=True, exist_ok=True)

    catalog = None
    if not args.no_catalog:
        print("opening asset catalogue for name resolution ...")
        catalog = AssetCatalog(AssetManager(str(dump)))

    archive = CacheArchive(find_czone(dump))
    exporter = ZoneExporter(catalog)
    print(f"CZone records: {len(archive)}")

    started = time.time()
    index: List[dict] = []
    written = 0
    skipped_unnamed = 0
    failed = 0

    ids = archive.ids()
    for zone_id in ids:
        zone = ArcZone()
        try:
            zone.load_binary(archive.stream(zone_id))
        except Exception as error:  # a zone this cannot read is reported, not swallowed
            failed += 1
            print(f"  FAILED {zone_id}: {type(error).__name__}: {error}")
            continue

        if args.named_only and not zone.zone_name:
            skipped_unnamed += 1
            continue

        record = exporter.zone(zone_id, zone)
        stem = f"{zone_id}_{slugify(zone.zone_name)}"
        (out / "placements" / f"{stem}.json").write_text(
            json.dumps(record, separators=(",", ":")), encoding="utf-8")
        index.append({
            "zoneId": zone_id,
            "name": zone.zone_name,
            "zoneType": zone.zone_type,
            "minorRadius": zone.zone_minor_radius,
            "majorRadius": zone.zone_major_radius,
            # Which city architectures may be built here. This is the other half of
            # `content/structures.json`'s `architecture`: the client refuses a placement
            # whose template tag is absent from this list, with
            # `PlaceError:ArchitectureCannotPlaceInZone` -- "This city architecture cannot
            # be placed in this zone." Without it that field cannot be evaluated at all.
            # 837 of the 861 zones carry an empty list; the playable continents carry
            # `["Feudal", "Irekei", "Northman", "Elven"]` or a subset.
            "architecture": list(getattr(zone, "zone_architecture", []) or []),
            "props": len(record["props"]),
            "spawns": len(record["spawns"]),
            "file": f"placements/{stem}.json",
        })
        written += 1
        if args.sample and written >= args.sample:
            break

    (out / "index.json").write_text(
        json.dumps({"generator": "tools/export_zones.py",
                    "unitsPerMetre": 2.903,
                    "zones": index}, indent=1), encoding="utf-8")

    # The file name per asset, so a staging tool joins on this alone rather than needing
    # `models/assets.json` as a second input. Absent when the models were not exported.
    files: Dict[int, dict] = {}
    models_path = Path(args.models)
    if models_path.exists():
        for row in json.loads(models_path.read_text(encoding="utf-8")):
            files[row["asset_id"]] = row
    else:
        print(f"note: {models_path} not found — required_models.json will carry no file names")

    required = []
    total_placements = sum(exporter.required.values())
    running = 0
    for rank, (asset_id, count) in enumerate(exporter.required.most_common(), 1):
        name, kind = exporter.describe(asset_id)
        model = files.get(asset_id)
        running += count
        required.append({
            "rank": rank,
            "assetId": asset_id,
            "name": name,
            "kind": kind,
            "placements": count,
            # Running share of all placements covered by this model and every one above it —
            # so "how much of the world do the top N draw" is read off, not recomputed.
            "cumulativeShare": round(running / total_placements, 5),
            "file": model["file"] if model else None,
            "bytes": model["bytes"] if model else None,
        })
    (out / "required_models.json").write_text(
        json.dumps({"generator": "tools/export_zones.py",
                    "note": "every distinct asset the world places, most-placed first",
                    "totalPlacements": total_placements,
                    "models": required}, indent=1), encoding="utf-8")

    # --- reconcile out loud: named == written + skipped + failed, or say so ---
    considered = len(ids) if not args.sample else written + skipped_unnamed + failed
    print()
    print(f"zones written {written}  unnamed skipped {skipped_unnamed}  failed {failed}")
    if not args.sample and written + skipped_unnamed + failed != len(ids):
        print(f"MISMATCH: {len(ids)} records but "
              f"{written + skipped_unnamed + failed} accounted for")
    placements = sum(row["props"] for row in index)
    spawns = sum(row["spawns"] for row in index)
    print(f"placements {placements}  spawns {spawns}")
    print(f"distinct models placed {len(exporter.required)}"
          f"  unresolved template ids {len(exporter.unresolved)}"
          f" ({sum(exporter.unresolved.values())} placements)")
    if exporter.unresolved:
        print("  unresolved:", ", ".join(
            f"{i}x{n}" for i, n in exporter.unresolved.most_common(10)))
    by_kind = Counter(row["kind"] for row in required if row["kind"])
    print("  by kind:", dict(by_kind))
    print(f"wrote {out}  in {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
