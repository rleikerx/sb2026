#!/usr/bin/env python3
"""
The animation lookup table: model -> sex -> equipment -> the clip that actually plays.

Why this exists
---------------
Every animation in this game is chosen by an **ANIMID**, and an ANIMID is not a clip.
It is a *slot number* in the skeleton's own animation table, and each skeleton fills
its slots from its own clip namespace. `bow` is ANIMID 137 for everyone; on a human it
resolves to clip 1000137 and on a minotaur to whatever that rig put in slot 137. That
indirection is the whole reason one config drives seventeen body plans.

`rig/skeletons.json` cannot express this. `ArcSkeleton.load_binary` keeps an animation
id only `if anim_id > 0`, so the 455-slot table for skeleton 1 arrives as a 247-entry
list with the holes closed up and every position shifted. Indexing it by ANIMID is
silently wrong -- 130 lands on 1000161 -- and every ANIMID at or above 247 is simply
out of range, which is why parry (294-301) could never be looked up at all.

This reads the table *uncompacted*, straight from Skeleton.cache, and joins it to every
source that names an ANIMID:

    Emotes.cfg          ANIMID          59 named emotes, 130-199
    Powers.cfg          LOOPANIMID      the pose a power holds while channelling
    PowerActions.cfg    ATTACKANIMS     the swing a power action plays
    COBJECT items       item_parry_anim_id, weapon_combat_idle_anim,
                        weapon_attack_anim_right/left  -- per weapon
    COBJECT race runes  rune_skeleton per sex

What it emits
-------------
    resolve.json    skeleton -> {animid: clipToken}, the full uncompacted table.
                    This is the file that makes an ANIMID mean something.
    actions.json    the ANIMID vocabulary: which id is which emote, power, parry, swing
    models.json     model -> skeleton, with race and sex where the model is a race rune
    items.json      item -> the ANIMIDs it selects, and its male/female render objects
    coverage.json   which (skeleton, action) pairs actually resolve, and which do not

Resolution is a two-step join, deliberately not materialised:

    skeleton = models[model].skeletonId
    animid   = items[weapon].parryAnimId          # or a power, or an emote
    clip     = resolve[skeleton].animid[animid]   # absent = this rig cannot do it

The cross product of 2,380 models and 811 weapons is not a table anybody wants; the two
maps that generate it are a few hundred kilobytes.

A caveat worth carrying: **sex changes the skeleton, always.** Every race that ships both
sexes uses a different rig for each -- male human is skeleton 1, female is 6 -- and there
is no race where the two share one. `content/races.json` records a single `skeleton_id`
per race, which is the male one; rigging a female character from it is wrong.

Usage:
    python tools/export_animation_table.py
    python tools/export_animation_table.py --out export_aegisfall/animations
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arcane.enums.arc_rune import RUNE_TYPE_TO_STRING
from arcane.objects.ArcItem import ArcItem
from arcane.objects.ArcRune import ArcRune
from arcane.util.ResStream import ResStream
from assets.cache_archive import CacheArchive

COBJECT_HEADER_SIZE = 8

ITEM_TYPE_NAMES = {
    0: "UNKNOWN", 1: "WEAPON", 2: "ARMOR", 3: "BASE", 4: "GOLD", 5: "SCROLL",
    6: "BOOK", 7: "WAND", 8: "POTION", 9: "KEY", 10: "CHARTER", 11: "GUILDTREE",
}


# --------------------------- the slot table ---------------------------

def slot_table(stream: ResStream) -> Optional[List[int]]:
    """
    Every animation slot in file order, holes included.

    `ArcSkeleton.load_binary` drops the zeros, which is the right shape for "what
    clips does this rig have" and the wrong one for "what is in slot 137". Each
    record is four dwords and only the second carries the id; the other three are
    zero in every record of every skeleton in this cache, checked.

    Returns None for the 'SKEL' magic variant, which carries no slot table at all.
    """
    start = stream.buffer.tell()
    head = stream.read_bytes(4)
    stream.buffer.seek(start)
    if head == b"SKEL":
        return None

    stream.read_string()                      # 'skeleton'
    count = stream.read_dword()
    slots: List[int] = []
    for _ in range(count):
        stream.read_dword()
        slots.append(stream.read_dword())
        stream.read_dword()
        stream.read_dword()
    return slots


# --------------------------- config readers ---------------------------

def named_animids(path: Path, key: str = "ANIMID") -> Dict[int, str]:
    """NAME=/ANIMID= pairs from a .cfg. The first NAME above an id owns it."""
    if not path.exists():
        return {}
    out: Dict[int, str] = {}
    current: Optional[str] = None
    for line in path.read_text(encoding="latin-1", errors="ignore").splitlines():
        name = re.match(r'\s*NAME=\s*"([^"]*)"', line)
        if name:
            current = name.group(1)
            continue
        found = re.match(r"\s*%s=\s*(\d+)" % key, line)
        if found and current is not None:
            out.setdefault(int(found.group(1)), current)
    return out


def keyed_animids(path: Path, key: str) -> Dict[int, List[str]]:
    """
    ANIMID -> the named entries that select it, for a config where many names share ids.

    Powers.cfg uses LOOPANIMID and reuses thirteen ids across 666 powers, so the useful
    direction is id -> names rather than the other way round.
    """
    if not path.exists():
        return {}
    out: Dict[int, set] = defaultdict(set)
    current: Optional[str] = None
    for line in path.read_text(encoding="latin-1", errors="ignore").splitlines():
        name = re.match(r'\s*NAME=\s*"([^"]*)"', line)
        if name:
            current = name.group(1)
            continue
        found = re.match(r"\s*%s=\s*(\d+)" % key, line)
        if found and int(found.group(1)):
            out[int(found.group(1))].add(current or "")
    return {k: sorted(v) for k, v in sorted(out.items())}


def attack_animids(path: Path) -> Dict[int, List[str]]:
    """ATTACKANIMS is a whitespace-separated list of ANIMIDs on a power action."""
    if not path.exists():
        return {}
    out: Dict[int, set] = defaultdict(set)
    current: Optional[str] = None
    for line in path.read_text(encoding="latin-1", errors="ignore").splitlines():
        name = re.match(r'\s*NAME=\s*"([^"]*)"', line)
        if name:
            current = name.group(1)
            continue
        found = re.match(r"\s*ATTACKANIMS=\s*([0-9 ]+)", line)
        if found:
            for value in found.group(1).split():
                if int(value):
                    out[int(value)].add(current or "")
    return {k: sorted(v) for k, v in sorted(out.items())}


# --------------------------- cobject readers ---------------------------

def cobject_rows(cache: Path):
    """
    (asset_id, type_code, parsed object) for every COBJECT this tool cares about.

    Only ITEM and RUNE carry an ANIMID, so the parser map is those two rather than
    `asset_manager.COBJECT_TYPE_PARSERS` -- importing that pulls in Pillow for a
    table of type codes, and this tool never touches an image.
    """
    parsers = {9: ArcItem, 13: ArcRune}
    archive = CacheArchive(cache)
    for asset_id in archive.ids():
        data = archive.read(asset_id)
        if not data or len(data) < COBJECT_HEADER_SIZE:
            continue
        type_code = struct.unpack_from("<I", data, 4)[0]
        parser = parsers.get(type_code)
        if parser is None:
            continue
        obj = parser()
        try:
            obj.load_binary(ResStream(data[COBJECT_HEADER_SIZE:]))
        except Exception:  # noqa: BLE001 - a record that will not parse has nothing to give
            continue
        yield asset_id, type_code, obj


def clean(text: Any) -> str:
    return text.strip() if isinstance(text, str) else ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", default=str(REPO_ROOT / "arcane_dump"))
    ap.add_argument("--config", default=str(REPO_ROOT / "export_aegisfall" / "config"))
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "animations"))
    args = ap.parse_args()

    dump = Path(args.dump)
    config = Path(args.config) / "Config"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()

    # -- resolve.json --------------------------------------------------
    skeleton_cache = next(iter(sorted(dump.rglob("Skeleton.cache"))), None)
    if skeleton_cache is None:
        print("Skeleton.cache not found", file=sys.stderr)
        return 1

    archive = CacheArchive(skeleton_cache)
    resolve: Dict[str, Any] = {}
    for skeleton_id in archive.ids():
        try:
            slots = slot_table(archive.stream(skeleton_id))
        except Exception:  # noqa: BLE001
            continue
        if not slots:
            continue
        filled = {str(i): token for i, token in enumerate(slots) if token}
        # A clip in more than one slot is the rig saying "these actions look the same".
        resolve[str(skeleton_id)] = {
            "slots": len(slots),
            "filled": len(filled),
            "distinctClips": len(set(filled.values())),
            "animid": filled,
        }

    # -- actions.json --------------------------------------------------
    emotes = named_animids(config / "Emotes.cfg")
    powers = keyed_animids(config / "Powers.cfg", "LOOPANIMID")
    actions = attack_animids(config / "PowerActions.cfg")

    # -- items.json + models.json --------------------------------------
    cobjects = next(iter(sorted(dump.rglob("CObjects.cache"))), None)
    if cobjects is None:
        print("CObjects.cache not found", file=sys.stderr)
        return 1

    items: Dict[str, Any] = {}
    models: Dict[str, Any] = {}
    parry_ids: Counter = Counter()
    idle_ids: Counter = Counter()
    swing_ids: Counter = Counter()

    for asset_id, type_code, obj in cobject_rows(cobjects):
        if type_code == 9:  # ITEM
            weapon = getattr(obj, "item_weapon", None)
            parry = int(getattr(obj, "item_parry_anim_id", 0) or 0)
            row: Dict[str, Any] = {
                "name": clean(getattr(obj, "obj_name", None))
                        or clean(getattr(obj, "item_base_name", None)),
                "baseName": clean(getattr(obj, "item_base_name", None)),
                "type": ITEM_TYPE_NAMES.get(getattr(obj, "item_type", 0), "UNKNOWN"),
                "equipSlots": getattr(obj, "item_eq_slots_value", None),
                "skillUsed": getattr(obj, "item_skill_used", None),
                "parryAnimId": parry or None,
                # Items ship two meshes. Picking the male one for a female character is
                # the same class of mistake as picking the male skeleton.
                "renderObject": getattr(obj, "obj_render_id", None),
                "renderObjectFemale": getattr(obj, "item_render_object_female", None) or None,
            }
            if parry:
                parry_ids[parry] += 1
            if weapon is not None:
                idle = int(getattr(weapon, "weapon_combat_idle_anim", 0) or 0)
                # Each entry is [ANIMID, weight]; the weights of a list sum to 100, so the
                # client is rolling a weighted choice, not cycling them in order.
                right = [[int(a), int(b)]
                         for a, b in (getattr(weapon, "weapon_attack_anim_right", None) or [])]
                left = [[int(a), int(b)]
                        for a, b in (getattr(weapon, "weapon_attack_anim_left", None) or [])]
                row.update({
                    "combatIdleAnimId": idle or None,
                    "attackAnimRight": right or None,
                    "attackAnimLeft": left or None,
                    "weaponSpeed": getattr(weapon, "weapon_wepspeed", None),
                    "maxRange": getattr(weapon, "weapon_max_range", None),
                })
                if idle:
                    idle_ids[idle] += 1
                for animid, _weight in right + left:
                    if animid:
                        swing_ids[animid] += 1
            items[str(asset_id)] = row

        elif type_code == 13:  # RUNE - races carry the skeleton, and the sex that picks it
            if RUNE_TYPE_TO_STRING.get(getattr(obj, "rune_type", None)) != "RACE":
                continue
            fields = obj.save_json()
            models[str(asset_id)] = {
                "name": clean(fields.get("obj_name")),
                "race": clean(fields.get("rune_sub_type")),
                "sex": fields.get("rune_sex"),
                "skeletonId": fields.get("rune_skeleton"),
                "renderable": fields.get("rune_renderable"),
            }

    action_rows = {
        "emote": {str(k): v for k, v in sorted(emotes.items())},
        "powerLoop": {str(k): v for k, v in powers.items()},
        "powerActionAttack": {str(k): v for k, v in actions.items()},
        "parry": {str(k): v for k, v in sorted(parry_ids.items())},
        "combatIdle": {str(k): v for k, v in sorted(idle_ids.items())},
        "weaponSwing": {str(k): v for k, v in sorted(swing_ids.items())},
    }

    # -- coverage.json -------------------------------------------------
    # The question a consumer actually asks: can THIS rig do THIS action at all?
    classes = {
        "emote": sorted(emotes),
        "powerLoop": sorted(powers),
        "powerActionAttack": sorted(actions),
        "parry": sorted(parry_ids),
        "combatIdle": sorted(idle_ids),
        "weaponSwing": sorted(swing_ids),
    }
    coverage: Dict[str, Any] = {}
    for skeleton_id, entry in resolve.items():
        filled = entry["animid"]
        coverage[skeleton_id] = {
            name: {"of": len(ids), "resolved": sum(1 for i in ids if str(i) in filled)}
            for name, ids in classes.items()
        }

    note = ("ANIMID is a slot index, not a clip id. resolve[skeleton].animid[animid] is the "
            "clip token; a missing key means that rig has no animation for that action. "
            "Sex changes the skeleton -- see models.json, never content/races.json.")
    generator = "tools/export_animation_table.py"
    for name, payload in (
        ("resolve.json", {"generator": generator,
                          "note": "full uncompacted slot table per skeleton",
                          "skeletons": resolve}),
        ("actions.json", {"generator": generator,
                          "note": "which ANIMID means what, by source",
                          "actions": action_rows}),
        ("models.json", {"generator": generator,
                         "note": "race runes: one entry per race AND sex",
                         "models": models}),
        ("items.json", {"generator": generator,
                        "note": "per item: the ANIMIDs it selects and its two render objects",
                        "items": items}),
        ("coverage.json", {"generator": generator, "note": note, "coverage": coverage}),
    ):
        (out / name).write_text(json.dumps(payload, indent=1), encoding="utf-8")

    weapons = sum(1 for r in items.values() if r["type"] == "WEAPON")
    print(f"skeletons {len(resolve)}  items {len(items)} (weapons {weapons})  "
          f"race models {len(models)}")
    print("ANIMID vocabulary: " + "  ".join(f"{k} {len(v)}" for k, v in action_rows.items()))
    print(f"wrote {out}  in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
