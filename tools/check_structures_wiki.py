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
`Architecture` and `Extras: not rankable` compare exactly -- the latter against
`max_ranks == 1`, which is what the client stores for a building placed at its only rank.

`Hirelings` is compared as presence rather than by name: the wiki names the NPC types a
building accepts (`Guard Captain`, `Banker`) where the cache stores a per-rank *count*.
Agreement here means both sources agree the building takes hirelings at all.

`Cost` is **not checkable from the cache** and is not a gap in this export. The wiki quotes
a builder's price (750k for a Barracks); the client ships no per-building deed carrying it
-- `items.json` has three deed rows in total, all generic, all value 0 or 1. Prices live
server-side.

`Size` (`4x2`) has no counterpart either. `template_zone_no_build` and
`template_zone_influence` are radii in world units, a different quantity from a grid
footprint, and guessing a mapping between them would manufacture agreement rather than
test for it.

The score
---------
All 52 sections match a template, and 102 of 107 comparable fields agree: architecture
43/44, `not rankable` 11/11, hirelings 48/52. **Every one of the five disagreements is a
wall**, in two groups, and both look like properties of the cache rather than of this
comparison.

  * `Irekei Outer Walls` is typed `Feudal`. The three templates building the Irekei wall
    pieces carry `architecture: ["Feudal"]`, where the Elven and Invorri gate, stair and
    straight sections are all typed correctly. Only their *cap* pieces are Feudal too, so
    this is not simply "walls are untyped" -- the Irekei set alone is styled wrong.
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default=str(REPO_ROOT / "export_aegisfall"))
    ap.add_argument("--cache", default=str(REPO_ROOT / ".wikicache" / "buildings.json"))
    args = ap.parse_args()

    rows = json.loads((Path(args.export) / "content" / "structures.json")
                      .read_text(encoding="utf-8"))
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

    print(f"{'building':<26}{'style':<10}{'arch':>6}{'rank':>6}{'hire':>6}")
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
        print(line)

    print("\nwiki building sections: " + str(len(found)))
    print("matched to a template: " + str(tally["matched"]))
    if unmatched:
        print("unmatched: " + str(unmatched))
    print(f"\n{'field':<22}{'compared':>9}{'agree':>7}{'differ':>8}")
    for key, label in (("arch", "Architecture"), ("rank", "Extras: not rankable"),
                       ("hire", "Hirelings (presence)")):
        total = tally[key + "_total"]
        if total:
            print(f"{label:<22}{total:>9}{tally[key]:>7}{total - tally[key]:>8}")
    checked = sum(tally[k + "_total"] for k in ("arch", "rank", "hire"))
    agreed = sum(tally[k] for k in ("arch", "rank", "hire"))
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
