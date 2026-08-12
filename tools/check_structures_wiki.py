#!/usr/bin/env python3
"""
Check `content/structures.json` against the Morloch wiki's `Buildings` page.

Why this exists, and why the earlier answer was wrong
-----------------------------------------------------
An earlier pass concluded the wiki *could not* check this file: of the 250 distinct
buildable structure names, only 7 exist as wiki pages, and only one of those carries a
rank table. That was true and it was the wrong question. **The buildings are not separate
pages -- they are 52 `=== sections ===` of a single `Buildings` page**, grouped under five
architecture headings, each with Cost, Hirelings, Extras and Size. Searching page titles
found 7 of them; reading the page finds all 52.

That is the same error as the two perfect scores in `check_disciplines_wiki.py`: a check
that does not cover the thing cannot clear it, and "the wiki has nothing on this" is a
claim about the search, not about the wiki. It stood for one pass and shaped a section of
the consumer guide.

The join, once the naming is right
----------------------------------
26 of the 52 match outright. The rest need three rules, all mechanical:

  * **The wiki drops the `Feudal ` prefix**, because Feudal is the default style -- its
    `Church` is the cache's `Feudal Church`. That alone is 9 of the 26 misses.
  * **`Invorii` on the wiki is `Invorri` in the cache.** One letter, 9 buildings.
  * **`Cottage [Log, Stone, Wood]` is three rows**, not one: the bracket lists the material
    prefixes, giving `Log Cottage`, `Stone Cottage`, `Wood Cottage`.

What is comparable, and what is not
-----------------------------------
`Extras: not rankable` compares exactly, against `max_ranks == 1`, which is what the client
stores for a building placed at its only rank.

`Architecture` needs one qualification. `template_architecture` is **not a style label**:
zones carry the same field and the client refuses a placement whose template tag is absent
from the zone's list -- `PlaceError:ArchitectureCannotPlaceInZone`, "This city architecture
cannot be placed in this zone". So the value is the set of zone architectures that will
accept the asset, which for an ordinary building is just its own style. That is why
grouping by it works, and it is why the test here is `style in architecture` rather than
equality: 9 templates carry more than one entry and all of them are trainer halls, where
the extra entries are biomes (`Elven Guild Hall` is `["Feudal", "Forest", "Mountains"]`).
Those are excluded from the architecture check for that reason -- the wiki groups them
under Trainer Buildings, which is not an architecture at all.

`Hirelings` is compared as presence rather than by name: the wiki names the NPC types a
building accepts (`Guard Captain`, `Banker`) where the cache stores a per-rank *count*.
Agreement here means both sources agree the building takes hirelings at all.

`Cost` **is** checkable, and an earlier version of this file said it was not. The reasoning
was that `items.json` holds three generic deed rows, all value 0 or 1, so prices had to be
server-side. True of `items.json`; false of the cache. Deeds are a **separate asset kind**
and it carries 880 of them, each with `item_value`, none of which `export_content.py` read.
They are now in `content/deeds.json` and every price the wiki quotes agrees exactly.

That makes three claims in this file's history that were statements about a search rather
than about the source: the buildings "not being on the wiki", and now the costs "not being
in the cache". Both times the missing thing was one lookup away in a place I had not
looked.

`Size` (`4x2`) has no counterpart. `template_zone_no_build` and `template_zone_influence`
are radii in world units, a different quantity from a grid footprint, and guessing a
mapping between them would manufacture agreement rather than test for it.

The score
---------
All 52 sections match a template, and 154 of 159 comparable fields agree: architecture
43/44, `not rankable` 11/11, hirelings 48/52, **cost 52/52**. The cost column is the
strongest single result in any of these comparisons -- 52 prices from 1,500,000 down to
50,000, read out of a different asset kind than the buildings themselves, matching a
player-written table exactly.

**Every one of the five disagreements is a wall**, in two groups, and both look like
properties of the cache rather than of this comparison.

  * `Irekei Outer Walls` is tagged `Feudal`. Templates 2000192/3/4 build the Irekei gate,
    stair and straight-wall pieces and carry `architecture: ["Feudal"]`, where the Elven
    (2000209/11/12) and Invorri (2000227/8/9) equivalents carry their own style. It is not
    that walls go untagged: **2000195 and 2000196, the Irekei towers, sit in the same
    contiguous id block, have the same dual-name shape, and are tagged `Irekei`.** Wall
    *caps* are Feudal in all three styles, which does look deliberate -- they are shared
    geometry, and the Invorri block's caps even build the unprefixed `Outer Wall Cap`
    structures.

    Left as the cache has it. Since the tag is a placement filter and the playable zones
    permit Feudal almost everywhere, the consequence is that those three appear under the
    Feudal list rather than the Irekei one -- an inconsistency with the block around them,
    not a building that cannot be placed. Overwriting it would put invented data into an
    export whose whole value is being what shipped.
  * **No wall template allows a hireling at any rank.** The wiki gives all four wall
    families `Archer Captain, Wall Archer, Tower Artillery Captain`; every wall template
    here reads `-1` at every rank, including the `Outer Wall with Tower` pieces, which
    reach `0` and no higher. If the wiki is right, wall garrisons are assigned
    server-side rather than capped by the template.

Both are reported rather than absorbed. The cache is authoritative -- it is what shipped --
but a disagreement is worth stating precisely enough that someone with a running server
can settle it.

    python tools/check_structures_wiki.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_powers_wiki import api  # one fetch implementation for all of these

# The wiki's architecture headings against the cache's `template_architecture`.
ARCHITECTURE = {"Feudal Buildings": "Feudal", "Elven Buildings": "Elven",
                "Invorii Buildings": "Northman", "Irekei Buildings": "Irekei",
                # The trainer buildings are guild halls; the cache spreads them across
                # styles rather than giving them one, so they are not architecture-checked.
                "Trainer Buildings": None}

# Four sections the wiki titles by their function where the cache names them outright.
# Each is settled by the wiki's own description rather than by string similarity:
#   War Temple  -- "the militant philosophy of the Temple of the Cleansing Flame"
#   Elven Shop  -- "Mercantiles offer adventurers a place to buy gear", i.e. the Elven one
#   Keep        -- "Keeps are the most utilitarian and the most defensible Guild Halls"
#   Cathedral   -- "administrative centers within the Church hierarchy"
TITLE_ALIAS = {"War Temple": "Temple of the Cleansing Flame",
               "Elven Shop": "Elven Mercantile",
               "Keep": "Guild Keep",
               "Cathedral": "Cathedral of the All Father"}

# `<style> Outer Walls` is one wiki section standing for a whole family of wall pieces --
# gates, corners, caps, stair sections. Feudal's carry no style prefix at all, and the two
# words are not always adjacent (`Elven Straight Outer Wall` against `Invorri Outer
# Straight Wall`), so this matches on both words rather than on a phrase.
WALL_STYLE_PREFIX = {"Feudal": "", "Elven": "Elven", "Northman": "Invorri",
                     "Irekei": "Irekei"}


def fetch(cache: Path) -> Dict[str, str]:
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    data = api(prop="revisions", rvprop="content", rvslots="main", titles="Buildings")
    pages = {p["title"]: p["revisions"][0]["slots"]["main"]["*"]
             for p in data["query"]["pages"].values() if p.get("revisions")}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(pages), encoding="utf-8")
    return pages


def flatten(text: str) -> str:
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    return re.sub(r"<[^>]+>", " ", text)


def candidates(title: str, style: Optional[str]) -> List[str]:
    """
    Every cache name a wiki section could be.

    `Cottage [Log, Stone, Wood]` expands to three; a bare Feudal name gains its prefix;
    `Invorii` becomes `Invorri`.
    """
    title = title.strip()
    if title in TITLE_ALIAS:
        return [TITLE_ALIAS[title]]
    bracket = re.search(r"\[([^\]]*)\]", title)
    base = re.sub(r"\s*\[[^\]]*\]", "", title).strip()
    names = ([f"{p.strip()} {base}" for p in bracket.group(1).split(",") if p.strip()]
             if bracket else [base])
    out = []
    for name in names:
        name = name.replace("Invorii", "Invorri")
        out.append(name)
        # Feudal is the default style, so the wiki writes `Church` for `Feudal Church`.
        if style == "Feudal" and not name.startswith("Feudal"):
            out.append("Feudal " + name)
    return out


def sections(text: str) -> List[tuple]:
    """
    (title, body, architecture) for each `=== building ===`, in page order.

    The level-2 split needs the `(?!=)` guard: without it `=== Barracks ===` matches the
    level-2 pattern too, every heading is read as a style, and the page parses to nothing.
    """
    out = []
    style = None
    parts = re.split(r"\n==(?!=) *(.+?) *==\s*\n", text)
    # [preamble, heading, body, heading, body, ...] -- headings are the odd indices, so
    # position decides what a chunk is rather than its content.
    for i in range(1, len(parts) - 1, 2):
        style = ARCHITECTURE.get(parts[i].strip())
        inner = re.split(r"\n=== *(.+?) *===", "\n" + parts[i + 1])
        for j in range(1, len(inner) - 1, 2):
            out.append((inner[j].strip(), flatten(inner[j + 1]), style))
    return out


def row_field(body: str, label: str) -> Optional[str]:
    """The `|'''Cost'''` / `|750k` two-cell rows these tables are built from."""
    found = re.search(r"'''%s'''\s*\n\|\s*([^\n|]*)" % re.escape(label), body)
    return found.group(1).strip() if found else None


def money(value: Optional[str]) -> Optional[int]:
    """`750k` -> 750000, `1.5m` -> 1500000."""
    found = re.match(r"([\d.]+)\s*([kmKM])?", (value or "").strip())
    if not found:
        return None
    scale = {"k": 1000, "m": 1_000_000}.get((found.group(2) or "").lower(), 1)
    return int(float(found.group(1)) * scale)


def deed_names(title: str, style: Optional[str]) -> List[str]:
    """
    The deed rows a wiki section could name.

    Deeds are named for the building, usually with ` Deed` appended -- `Barracks Deed`,
    `Irekei Citadel Deed` -- but the wall sets and the siege tent carry the bare name.
    Unlike the structure join this needs no `Feudal ` prefix: the deeds use the wiki's own
    bare spelling, which is a second sign the wiki was written off the builder's list.

    `Cottage [Log, Stone, Wood]` expands the same way it does for structures, and has to:
    the three material variants are three separate deeds, all priced the same.
    """
    title = title.strip().replace("Invorii", "Invorri")
    bracket = re.search(r"\[([^\]]*)\]", title)
    base = re.sub(r"\s*\[[^\]]*\]", "", title).strip()
    bases = ([f"{p.strip()} {base}" for p in bracket.group(1).split(",") if p.strip()]
             if bracket else [base])
    return [name + suffix for name in bases for suffix in (" Deed", "")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default=str(REPO_ROOT / "export_aegisfall"))
    ap.add_argument("--cache", default=str(REPO_ROOT / ".wikicache" / "buildings.json"))
    args = ap.parse_args()

    content = Path(args.export) / "content"
    rows = json.loads((content / "structures.json").read_text(encoding="utf-8"))
    # `deeds.json` is what makes Cost checkable; this file used to say it was not.
    deeds: Dict[str, List[dict]] = defaultdict(list)
    deed_file = content / "deeds.json"
    if deed_file.exists():
        for deed in json.loads(deed_file.read_text(encoding="utf-8")):
            deeds[deed["name"]].append(deed)
    # A building's attributes live on the template whose ranks put it down, so the lookup
    # goes name -> template rather than name -> structure.
    by_building: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        for name in row.get("building_names") or []:
            by_building[name].append(row)

    text = fetch(Path(args.cache))["Buildings"]
    found = sections(text)
    tally: Counter = Counter()
    misses: List[str] = []
    unmatched: List[str] = []
    unpriced: List[str] = []

    print(f"{'building':<26}{'style':<10}{'arch':>6}{'rank':>6}{'hire':>6}{'cost':>6}")
    for title, body, style in found:
        templates: List[dict] = []
        if title.endswith("Outer Walls"):
            prefix = WALL_STYLE_PREFIX.get(style or "", "")
            for name, found_rows in by_building.items():
                lowered = name.lower()
                if "outer" not in lowered or "wall" not in lowered:
                    continue
                # Feudal's wall pieces are the ones carrying no style prefix at all.
                styled = name.split()[0] in WALL_STYLE_PREFIX.values() and name.split()[0]
                if (styled or "") == prefix:
                    templates += found_rows
        else:
            for name in candidates(title, style):
                templates += by_building.get(name, [])
        if not templates:
            unmatched.append(title)
            continue
        tally["matched"] += 1
        line = f"{title[:25]:<26}{str(style or '-'):<10}"

        def verdict(label: str, ok: Optional[bool]) -> str:
            if ok is None:
                return f"{'-':>6}"
            tally[label + "_total"] += 1
            tally[label] += ok
            return f"{('OK' if ok else 'X'):>6}"

        if style:
            ok = any(style in (t.get("architecture") or []) for t in templates)
            line += verdict("arch", ok)
            if not ok:
                misses.append(f"{title} architecture: wiki {style!r} ours "
                              f"{[t.get('architecture') for t in templates]}")
        else:
            line += f"{'-':>6}"

        extras = (row_field(body, "Extras") or "").lower()
        if "not rankable" in extras:
            ok = any(t.get("max_ranks") == 1 for t in templates)
            line += verdict("rank", ok)
            if not ok:
                misses.append(f"{title} rankable: wiki says not rankable, ours max_ranks "
                              f"{[t.get('max_ranks') for t in templates]}")
        else:
            # The wiki only states the negative, so silence is not a claim either way.
            line += f"{'-':>6}"

        hirelings = (row_field(body, "Hirelings") or "").strip(" -")
        if hirelings:
            ok = any(any(r.get("hirelings", 0) > 0 for r in t.get("ranks") or [])
                     for t in templates)
            line += verdict("hire", ok)
            if not ok:
                misses.append(f"{title} hirelings: wiki {hirelings!r} ours none on any rank")
        else:
            line += f"{'-':>6}"

        stated = money(row_field(body, "Cost"))
        priced = [d for name in deed_names(title, style) for d in deeds.get(name, [])]
        if stated is not None and priced:
            ok = any(d.get("value") == stated for d in priced)
            line += verdict("cost", ok)
            if not ok:
                misses.append(f"{title} cost: wiki {stated} ours "
                              f"{[d.get('value') for d in priced]}")
        else:
            line += f"{'-':>6}"
            if stated is not None:
                unpriced.append(title)
        print(line)

    print("\nwiki building sections: " + str(len(found)))
    print("matched to a template: " + str(tally["matched"]))
    if unmatched:
        print("unmatched: " + str(unmatched))
    print(f"\n{'field':<22}{'compared':>9}{'agree':>7}{'differ':>8}")
    for key, label in (("arch", "Architecture"), ("rank", "Extras: not rankable"),
                       ("hire", "Hirelings (presence)"), ("cost", "Cost (deed value)")):
        total = tally[key + "_total"]
        if total:
            print(f"{label:<22}{total:>9}{tally[key]:>7}{total - tally[key]:>8}")
    if unpriced:
        print("wiki quotes a cost, no deed row found: " + str(unpriced))
    checked = sum(tally[k + "_total"] for k in ("arch", "rank", "hire", "cost"))
    agreed = sum(tally[k] for k in ("arch", "rank", "hire", "cost"))
    print(f"\n{agreed}/{checked} agree")
    if misses:
        print("disagreements -- read each one before assuming the cache is wrong:")
        for m in misses[:12]:
            print("   " + m)
    else:
        print("every comparable field agrees")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
