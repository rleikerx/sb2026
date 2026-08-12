#!/usr/bin/env python3
"""
Extract mechanical game data from the client cache as JSON.

Character and item numbers live in the COBJECT records the client shipped, so
they can be read directly rather than scraped from a wiki. Same data, one step
closer to the source: re-runnable against a different cache and diffable.

What it emits (mechanical data only - no lore or description prose):

    races.json        base + cap attributes, creation cost, health/mana/stamina,
                      movement speeds, and which classes accept each race
    classes.json      base classes: attribute adjustments, granted skills,
                      eligible races
    disciplines.json  discipline runes and their requirements
    talents.json      talent runes
    items.json        equippable items: slot, weight, value, damage, requirements
    deeds.json        the 880 buildable deeds: price, what they place, start rank
    structures.json   buildings: rank progression, health, and the mesh that
                      renders each rank

Usage:
    python tools/export_content.py --out export_aegisfall/content
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arcane.util import ResStream
from arcane.enums.arc_rune import RUNE_TYPE_TO_STRING
from assets.asset_manager import AssetManager, COBJECT_TYPE_PARSERS, COBJECT_HEADER_SIZE
from assets.asset_catalog import AssetCatalog, AssetKind

STAT_ORDER = ["Strength", "Dexterity", "Constitution", "Intelligence", "Spirit"]

# The one place this export deliberately departs from the cache.
#
# These three templates build the Irekei outer-wall gate, stair and straight sections and
# are tagged `["Feudal"]`, where the Elven (2000209/11/12) and Invorri (2000227/8/9)
# equivalents each carry their own style. Three independent things say Irekei:
#
#   * the structures they build are ids 1309200-1310000, one contiguous Irekei block
#     whose other members are named `Irekei Outer Wall Gate`, `Irekei Outer Wall with
#     Stairs`, `Irekei Outer Straight Wall`. The unprefixed names inside it are Irekei
#     assets that were never renamed, not Feudal ones;
#   * templates 2000195/2000196, the Irekei towers, sit in the same contiguous template
#     block with the same dual-name shape and are tagged `Irekei`;
#   * the Morloch wiki lists Irekei Outer Walls as ordinary Irekei buildings.
#
# The wall *caps* are left alone on purpose. They are tagged Feudal in every style --
# including 2000207/2000208, which build structures actually named `Elven Outer Wall Cap`
# -- so uniform rather than anomalous, and a rule this has no standing to overturn.
#
# Where this applies, `architecture_shipped` carries the cache's own value so nothing is
# lost and the change is auditable. Delete this map to get the raw export back.
ARCHITECTURE_CORRECTIONS = {
    2000192: ["Irekei"],   # Irekei Outer Wall Gate
    2000193: ["Irekei"],   # Irekei Outer Wall with Stairs
    2000194: ["Irekei"],   # Irekei Outer Straight Wall
}


def signed32(v: Any) -> Any:
    """Attribute deltas are stored unsigned; -10 arrives as 4294967286."""
    if isinstance(v, int) and v >= 0x80000000:
        return v - 0x100000000
    return v


def clean(text: Optional[str]) -> str:
    return "".join(ch for ch in (text or "") if ch.isprintable()).strip()


def allowed(requirement, key: str, universe) -> Optional[List[str]]:
    """
    Who may use this, from a `{restrict, races|classes}` record.

    **The `restrict` flag inverts the list, and reading the list without it gets the
    answer exactly backwards.** Confirmed against the Morloch wiki by
    `tools/check_disciplines_wiki.py`: honouring the flag takes discipline race agreement
    from 41/171 to 171/171 and class agreement from 175/214 to 214/214.

        restrict False, list        the list is who MAY take it        -> that list
        restrict True,  list        the list is who may NOT             -> everyone else
        restrict True,  empty       nothing excluded, so anyone may     -> None
        restrict False, empty       an empty allow-list, so no one may  -> []

    The third case is why this returns `None` rather than `[]` for unrestricted. The old
    code emitted `[]` for it, which reads just as naturally as "nobody may" -- and it did
    so on 3,177 of the 4,021 items. `None` says "no restriction" and cannot be confused
    with an empty allow-list, which is the fourth case and genuinely does mean nobody:
    three items carry it (Lightning Spear, Alchemist's Cowl, Alchemist's Robes).

    The universe an exclusion is subtracted from is passed in rather than assumed, so a
    different cache resolves against its own contents.
    """
    requirement = requirement or {}
    listed = [x for x in (requirement.get(key) or []) if x]
    if not requirement.get("restrict"):
        return listed
    if not listed:
        return None
    excluded = set(listed)
    return [u for u in universe if u not in excluded]


def category_name(value) -> Optional[str]:
    """`rune_sub_type` as a name, or None when it is a hash or absent."""
    return (clean(value) or None) if isinstance(value, str) else None


def category_hash(value) -> Optional[int]:
    """`rune_sub_type` as a hash, for the 15 talents whose name did not resolve."""
    return value if isinstance(value, int) and value else None


def attr_map(entries) -> Dict[str, int]:
    """[{attr_type, attr_value}] -> {stat: value}, ordered like the stat sheet."""
    out: Dict[str, int] = {}
    for e in entries or []:
        if isinstance(e, dict) and "attr_type" in e:
            out[str(e["attr_type"])] = signed32(e.get("attr_value", 0))
    return {k: out[k] for k in STAT_ORDER if k in out} | {
        k: v for k, v in out.items() if k not in STAT_ORDER
    }


def raw_object(am: AssetManager, asset_id: int):
    data = am.archives["cobject"].read(asset_id)
    if data is None or len(data) < COBJECT_HEADER_SIZE:
        return None, None
    type_code = struct.unpack_from("<I", data, 4)[0]
    parser = COBJECT_TYPE_PARSERS.get(type_code)
    if parser is None:
        return None, None
    obj = parser()
    obj.load_binary(ResStream(data[COBJECT_HEADER_SIZE:]))
    return type_code, obj


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", default=str(REPO_ROOT / "arcane_dump"))
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "content"))
    args = ap.parse_args()

    am = AssetManager(args.dump)
    catalog = AssetCatalog(am)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    races: Dict[str, dict] = {}
    classes: List[dict] = []
    disciplines: List[dict] = []
    talents: List[dict] = []

    for asset_id in catalog.iter_asset_ids(AssetKind.CREATURE):
        _, obj = raw_object(am, asset_id)
        if obj is None:
            continue
        fields = obj.save_json()
        rune_type = RUNE_TYPE_TO_STRING.get(getattr(obj, "rune_type", None))
        name = clean(fields.get("obj_name"))

        common = {
            "asset_id": asset_id,
            "name": name,
            "icon_texture_id": fields.get("obj_icon") or None,
            "creation_cost": fields.get("rune_creation_cost"),
            "attributes": attr_map(fields.get("rune_attr_adj")),
            "attribute_caps": attr_map(fields.get("rune_max_attr_adj")),
        }

        if rune_type == "RACE":
            # Races appear once per sex/body variant; keep one entry per race
            # and record the variants that render it.
            key = clean(fields.get("rune_sub_type")) or name
            entry = races.setdefault(key, {
                **common,
                "race": key,
                "health": fields.get("rune_health"),
                "mana": fields.get("rune_mana"),
                "stamina": fields.get("rune_stamina"),
                "speeds": fields.get("rune_speed"),
                "standard_creation": fields.get("rune_is_standard_character_creation"),
                # First variant's rig, kept for callers that already read it. It is the
                # MALE one for every dual-sex race, so it is the wrong rig for half of
                # them — the per-variant `skeleton_id` below is the one to bind to.
                "skeleton_id": fields.get("rune_skeleton"),
                "variants": [],
                "classes": [],
            })
            entry["variants"].append({
                "asset_id": asset_id,
                "sex": fields.get("rune_sex"),
                # Sex changes the skeleton, always: no race that ships both sexes shares
                # a rig between them (male human is 1, female is 6).
                "skeleton_id": fields.get("rune_skeleton"),
                "icon_texture_id": fields.get("obj_icon") or None,
            })
        elif rune_type in ("CLASS", "DISCIPLINE", "TALENT"):
            row = {
                **common,
                "rune_type": rune_type,
                # Resolved below, once the loop has seen enough races and classes to
                # know what "everyone else" means.
                "_race_req": fields.get("item_race_req"),
                "_class_req": fields.get("item_class_req"),
                "level_req": fields.get("item_level_req"),
                "pracs_per_level": fields.get("rune_pracs_per_level"),
                # Which of the 240 talents a player may actually pick at creation. 92
                # are flagged; the other 148 are NPC runes (`Archer Mob`, `Belgosch
                # Lord`) that sit in the same table and are not selectable.
                "standard_creation": bool(
                    fields.get("rune_is_standard_character_creation")),
                # The mutual-exclusion group -- the wiki's "Rune Category". Two runes
                # sharing one are alternatives: only one `Blood Gift` may be taken.
                # 15 talents store an unresolved string hash here instead of a name;
                # those keep the hash in `rune_category_hash` rather than losing it,
                # and it resolves against no string this export or the client's own
                # hash table contains.
                "rune_category": category_name(fields.get("rune_sub_type")),
                "rune_category_hash": category_hash(fields.get("rune_sub_type")),
                "rank": fields.get("rune_rank") or None,
                # The stat floor for taking this rune, e.g. Ambidexterity needs Dex 50.
                "attribute_requirements": attr_map(fields.get("item_attr_req")),
                # Passive effects the bearer gets, keyed into `effects.json`.
                "applies_effects": [
                    {"effect": clean(p.get("power")), "arguments": p.get("arguments") or []}
                    for p in (fields.get("item_user_power_action") or [])
                    if isinstance(p, dict) and p.get("power")
                ],
                # Powers the rune teaches, keyed into `powers.json`, with the level it
                # is granted at.
                "power_grants": [
                    {"power": clean(p.get("power_type")), "value": p.get("power_value")}
                    for p in (fields.get("item_power_grant") or [])
                    if isinstance(p, dict) and p.get("power_type")
                ],
                "skill_grants": [
                    {"skill": s.get("skill_type"), "value": signed32(s.get("skill_value", 0))}
                    for s in (fields.get("rune_skill_grant") or []) if isinstance(s, dict)
                ],
                "skill_adjustments": [
                    {"skill": s.get("skill_type"),
                     "adjustments": [[signed32(a) for a in pair] for pair in s.get("skill_adjusts") or []]}
                    for s in (fields.get("rune_skill_adj") or []) if isinstance(s, dict)
                ],
            }
            {"CLASS": classes, "DISCIPLINE": disciplines, "TALENT": talents}[rune_type].append(row)

    # The universes an exclusion list is subtracted from. Both are read from what this
    # run actually found rather than hardcoded, so a different cache resolves against its
    # own contents: the 12 races flagged for character creation, and the player classes,
    # which excludes `Pet` because it is a rune type rather than something anyone rolls.
    playable_races = [r for r, v in races.items() if v.get("standard_creation")]
    player_classes = [c["name"] for c in classes if c["name"] != "Pet"]
    for row in classes + disciplines + talents:
        row["eligible_races"] = allowed(row.pop("_race_req"), "races", playable_races)
        row["required_classes"] = allowed(row.pop("_class_req"), "classes", player_classes)

    # Cross-link: which classes each race may take. `None` means unrestricted, which is
    # every race rather than none -- the distinction this back-fill would otherwise drop.
    for row in classes:
        # `Pet` is a rune type rather than something anyone rolls, and it is unrestricted,
        # so without this it lands in every race's class list.
        if row["name"] == "Pet":
            continue
        for race_name in (row["eligible_races"] if row["eligible_races"] is not None
                          else list(races)):
            if race_name in races:
                races[race_name]["classes"].append(row["name"])

    # ---- items ---------------------------------------------------------
    items: List[dict] = []
    for asset_id in catalog.iter_asset_ids(AssetKind.ITEM):
        _, obj = raw_object(am, asset_id)
        if obj is None:
            continue
        f = obj.save_json()
        items.append({
            "asset_id": asset_id,
            "name": clean(f.get("obj_name")),
            "base_name": clean(f.get("item_base_name")),
            "icon_texture_id": f.get("obj_icon") or None,
            "type": f.get("item_type"),
            "equip_slots": [s for s in (f.get("item_eq_slots_or") or []) if s != "NONE"],
            "weight": f.get("item_wt"),
            "value": f.get("item_value"),
            # Damage and the weapon numbers live in a nested `item_weapon` record, not on
            # the item. This used to read `item_min_damage`/`item_max_damage`, which are
            # not fields any item has, so every one of the 4,021 rows shipped
            # `damage: [null, null]` -- an advertised column that was empty end to end. It
            # was found by comparing against the Morloch wiki, which quotes a damage range
            # for weapons this export had none for.
            #
            # Kept as a list because the source is one, with the type on each entry: 785 of
            # the 811 weapons carry exactly one, and no item in this cache carries two.
            "damage": [
                {"type": d.get("damage_type"),
                 "min": d.get("damage_min"),
                 "max": d.get("damage_max")}
                for d in ((f.get("item_weapon") or {}).get("weapon_damage") or [])
            ],
            "weapon": ({"speed": weapon.get("weapon_wepspeed"),
                        "maxRange": weapon.get("weapon_max_range"),
                        "projectileId": weapon.get("weapon_projectile_id") or None,
                        "projectileSpeed": weapon.get("weapon_projectile_speed") or None}
                       if (weapon := f.get("item_weapon")) else None),
            "level_req": f.get("item_level_req"),
            "rank_req": f.get("item_rank_req"),
            "skill_used": f.get("item_skill_used"),
            "eligible_races": allowed(f.get("item_race_req"), "races", playable_races),
            "eligible_classes": allowed(f.get("item_class_req"), "classes",
                                        player_classes),
            "flags": list(f.get("item_flags") or []),
        })

    # ---- structures ----------------------------------------------------
    structures: List[dict] = []
    for asset_id in catalog.iter_asset_ids(AssetKind.STRUCTURE):
        _, obj = raw_object(am, asset_id)
        if obj is None:
            continue
        f = obj.save_json()
        cobj = am.load_cobject(asset_id)
        ranks = []
        for rank in f.get("template_rank_info") or []:
            if not isinstance(rank, dict):
                continue
            ranks.append({
                "rank": signed32(rank.get("rank_rank")),
                "health": rank.get("rank_health"),
                "hirelings": signed32(rank.get("rank_hirelings")),
                "buildings": [b[1] for b in rank.get("rank_building_id") or [] if len(b) >= 2],
            })
        structures.append({
            "asset_id": asset_id,
            # Two different record types share this table, and every row is missing the
            # other one's columns. 294 are buildable *templates*: they carry the
            # `template_*` fields and the rank ladder, and no `obj_name` at all. The other
            # 768 are the *structures* those ranks build: named, with health, floors and
            # doors, and no ranks. The two sets are disjoint -- no row has both -- so a
            # reader filtering on `ranks` or on `name` silently gets one half.
            "kind": "template" if ranks else "structure",
            "name": clean(f.get("obj_name")),
            "icon_texture_id": f.get("obj_icon") or None,
            # `combat_health_full` reads 0.0 on all 768 structures that carry it and is
            # absent on the 294 templates, so this column is empty in this build. Kept
            # rather than dropped: "the field exists and is zero" is a different statement
            # from "the field was not read", and the per-rank `health` below is the real one.
            "health": f.get("combat_health_full"),
            "template_id": getattr(cobj, "template_id", None),
            "render_ids": list(getattr(cobj, "render_ids", []) or []),
            "ranks": ranks,
            # **A zone-placement tag, not a style label**, though for an ordinary
            # building the two coincide and the wiki groups its list by it.
            #
            # Zones carry the same field (`zone_architecture`, now in
            # zones/index.json), and the client refuses a placement whose template tag
            # is absent from the zone's list -- `PlaceError:ArchitectureCannotPlaceInZone`,
            # "This city architecture cannot be placed in this zone." So this is the set
            # of zone architectures that will accept the asset.
            #
            # That is why the vocabulary is mixed: alongside Feudal/Elven/Northman/Irekei
            # it carries biome tokens, and the 9 templates with more than one entry are
            # all trainer halls -- `Elven Guild Hall` is `["Feudal", "Forest",
            # "Mountains"]`, which is where it may go rather than what it looks like.
            # `Invorri` here against the wiki's `Invorii`. Empty on 4 templates.
            #
            # Corrected on exactly three templates -- see ARCHITECTURE_CORRECTIONS. Where
            # that applies, `architecture_shipped` below carries the cache's own value.
            "architecture": ARCHITECTURE_CORRECTIONS.get(
                asset_id, f.get("template_architecture") or []),
            # `max_ranks` 1 is the wiki's "not rankable": the building is placed at its
            # only rank and never upgrades. 139 of the 294 templates are like this.
            "max_ranks": f.get("template_max_ranks"),
            "start_rank": f.get("template_start_rank"),
            "asset_type": f.get("template_asset_type"),
            "is_maintenance": f.get("template_is_maintenance"),
            "has_keys": f.get("template_has_keys"),
            # City footprint: how far this projects influence, and how close anything
            # else may be built. Both in world units -- divide by reference/summary.json's
            # `unitsPerMetre` for metres.
            "zone_influence": f.get("template_zone_influence") or [],
            "zone_no_build": f.get("template_zone_no_build") or [],
            # Which NPCs may be stationed here, as category and type ids.
            "valid_npc_categories": f.get("template_valid_npc_cat") or [],
            "valid_npc_types": f.get("template_valid_npc_type") or [],
            "terrain": f.get("template_terrain") or [],
            # 9 templates embed a second template outright rather than referencing one.
            "embeds_template": bool(f.get("has_embedded_template")),
            # Geometry, on the structure half of the table rather than the template half.
            "floors": f.get("structure_floors") or [],
            "levels": f.get("structure_levels") or [],
            "doors": f.get("structure_doors") or [],
            "has_platform": bool(f.get("static_has_platform")),
        })
        # Present only where this export overrode the cache, so a consumer that wants the
        # shipped value can always recover it and a diff shows the departure.
        if asset_id in ARCHITECTURE_CORRECTIONS:
            structures[-1]["architecture_shipped"] = (
                f.get("template_architecture") or [])

    # A template has no name of its own, which left 294 rows shipping `name: ""` and no way
    # to tell a Tree of Life from an Orc Slave Pen. Its identity is in the buildings its
    # ranks put down: 285 of the 294 reference exactly one named structure, and the 9 that
    # reference several are progressions -- 2000000 runs Tree of Life, then Belligerent
    # Palace, then Feudal Palace, which is a city tree upgrading and worth seeing in order.
    by_id = {s["asset_id"]: s["name"] for s in structures if s["name"]}
    for entry in structures:
        names: List[str] = []
        for rank in entry["ranks"]:
            for building in rank["buildings"]:
                found = by_id.get(building)
                if found and found not in names:
                    names.append(found)
        if names:
            entry["building_names"] = names

    # --- deeds -----------------------------------------------------------------------
    #
    # `AssetKind.DEED` was not read at all, which is why this export said building costs
    # were server-side: `items.json` carries three generic deed rows, and the 880 real
    # ones live in their own kind. Each carries `item_value`, and those values are the
    # prices the wiki quotes -- all 48 buildings it costs agree exactly.
    #
    # `deed_structure_id` is three different things depending on the deed, so it is
    # emitted raw and resolved only where the resolution is real. See `references` below.
    kind_of: Dict[int, str] = {}
    for kind in AssetKind:
        for asset_id in catalog.iter_asset_ids(kind):
            kind_of[asset_id] = kind.name

    deeds: List[dict] = []
    for asset_id in catalog.iter_asset_ids(AssetKind.DEED):
        _, obj = raw_object(am, asset_id)
        if obj is None:
            continue
        f = obj.save_json()
        target = f.get("deed_structure_id")
        # Ids below 10,000 are an index into a server-side table rather than an asset id
        # -- `Feudal Outer Walls` is 1, `Trebuchet` 10, `Healer Trainer` 103 -- and they
        # collide with real low-numbered props and creatures. Resolving them would
        # manufacture 489 wrong joins, so only ids in asset space are resolved.
        resolved = (kind_of.get(target) if isinstance(target, int) and target >= 10000
                    else None)
        deeds.append({
            "asset_id": asset_id,
            "name": clean(f.get("obj_name")),
            "icon_texture_id": f.get("obj_icon") or None,
            # The builder's price, and the wiki's `Cost` column.
            "value": f.get("item_value"),
            "weight": f.get("item_wt"),
            "deed_type": f.get("deed_type"),
            "target_id": target,
            # `STRUCTURE` on 153 (the building deeds, joining to structures.json),
            # `PROP` on ~220 (the furniture deeds), null on the rest -- either a
            # server-side index or, on the 18 charters, absent entirely.
            "target_kind": resolved,
            "start_rank": f.get("deed_start_rank"),
            "is_fortress": bool(f.get("deed_is_fortress")),
            "employment": f.get("deed_employment"),
            "eligible_races": allowed(f.get("item_race_req"), "races", playable_races),
            "eligible_classes": allowed(f.get("item_class_req"), "classes",
                                        player_classes),
        })

    tables = {
        "races.json": sorted(races.values(), key=lambda r: r["race"]),
        "classes.json": sorted(classes, key=lambda r: r["name"]),
        "disciplines.json": sorted(disciplines, key=lambda r: r["name"]),
        "talents.json": sorted(talents, key=lambda r: r["name"]),
        "items.json": items,
        "structures.json": structures,
        "deeds.json": sorted(deeds, key=lambda r: (r["name"], r["asset_id"])),
    }
    corrected = [s for s in structures if "architecture_shipped" in s]
    if corrected:
        print(f"architecture corrected on {len(corrected)} templates: "
              + ", ".join(f"{s['asset_id']} {s['architecture_shipped']}->"
                          f"{s['architecture']}" for s in corrected))

    for filename, rows in tables.items():
        with (out_dir / filename).open("w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2)
        print(f"{filename:20s} rows={len(rows)}")

    print(f"\ncontent|out={out_dir}")
    sample = tables["races.json"][0] if tables["races.json"] else None
    if sample:
        print(f"sample race: {sample['race']} cost={sample['creation_cost']} "
              f"attrs={sample['attributes']} caps={sample['attribute_caps']}")
        print(f"  classes={sample['classes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
