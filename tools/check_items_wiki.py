#!/usr/bin/env python3
"""
Check `content/items.json` against the Morloch wiki's weapon and armour pages.

Why this exists
---------------
Same reasoning as `tools/check_powers_wiki.py`: the wiki was written by players reading the
game, not by this repo reading the cache, so it agrees or disagrees for reasons that have
nothing to do with how the parse was written.

It has already earned its keep. `items.json` advertised a `damage` column and shipped
`[null, null]` on **all 4,021 rows**, because `export_content.py` read `item_min_damage` and
`item_max_damage` -- two fields no item has. The real numbers are in a nested `item_weapon`
record as `weapon_damage`, a list of `{damage_type, damage_min, damage_max}`. Nothing
internal could catch that: an always-null column is perfectly self-consistent. The wiki
quoting "8 - 34" for a weapon this export had no damage for is what caught it.

Reading the result
------------------
About half of each field matches exactly and the rest does not, with **no single scale
factor** between them -- the ratio of wiki damage to ours is 1.0 far more often than
anything else, and the remainder is scattered. That is the signature of the wiki
documenting a different patch, not of a decoding error: a wrong field agrees ~0% of the
time, which is exactly what this reported before the fix.

So the exact-match count is the useful number, and it is a floor rather than a score. Where
the two differ the cache is authoritative -- it is what shipped.

Armour, and the same defect a second time
-----------------------------------------
This file checked weapons and nothing else for its whole life, and the reason it could not
check armour is that **`items.json` had no armour statistic to check.** 2,361 rows are
ARMOR and none of them carried a protection value; `item_defense_rating` sits on 1,574 of
them, unread. A weapon table with no damage and an armour table with no armour are the same
defect, and only the first had been found -- because the first was the only one this
comparison covered.

`Category:Armor` is 35 pages of `Name | Skill | Defense | Block Chance | Durability |
Weight | Requirement` row tables, 751 rows, 49 of them naming an item this cache has. All
three comparable columns land at roughly the same two-thirds exact rate as the weapons,
with a scattered remainder -- the patch-drift signature rather than a decoding error.

**`durability` is a third instance of the same thing, smaller.** `parse_weapon` has pulled
`Durability:` off the wiki since the day this file was written, and the field was never in
the comparison loop, because `items.json` had no such column for it to be compared against.
It was read, discarded, and counted zero times, on every run, silently. It now compares on
221 weapons and 49 armour pieces.

Three times, the same shape: the check only ever asked about the columns the export
happened to have.

    python tools/check_items_wiki.py

Fetches Category:Weapons and Category:Armor through the MediaWiki API in batches of 20 with
a pause between calls, and caches under `.wikicache/` so a re-run costs nothing.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_powers_wiki import api  # one fetch implementation, not two

# The wiki writes ranges with a hyphen, an en dash, an em dash, or a mojibake replacement
# character where an en dash did not survive an edit. All four appear in these 264 pages.
DASH = r"[-–—�]"


def fetch_weapons(cache: Path) -> Dict[str, str]:
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    titles, cont = [], None
    while True:
        kw = dict(list="categorymembers", cmtitle="Category:Weapons", cmlimit="500")
        if cont:
            kw["cmcontinue"] = cont
        data = api(**kw)
        titles += [m["title"] for m in data["query"]["categorymembers"]]
        cont = data.get("continue", {}).get("cmcontinue")
        if not cont:
            break
        time.sleep(0.5)
    pages: Dict[str, str] = {}
    for i in range(0, len(titles), 20):
        data = api(prop="revisions", rvprop="content", rvslots="main",
                   titles="|".join(titles[i:i + 20]))
        for page in data["query"]["pages"].values():
            revisions = page.get("revisions")
            if revisions:
                pages[page["title"]] = revisions[0]["slots"]["main"]["*"]
        time.sleep(0.6)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(pages), encoding="utf-8")
    return pages


def fetch_category(cache: Path, category: str) -> Dict[str, str]:
    """Every page in a category, as wikitext. Cached."""
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    titles, cont = [], None
    while True:
        kw = dict(list="categorymembers", cmtitle=category, cmlimit="500")
        if cont:
            kw["cmcontinue"] = cont
        data = api(**kw)
        titles += [m["title"] for m in data["query"]["categorymembers"]]
        cont = data.get("continue", {}).get("cmcontinue")
        if not cont:
            break
        time.sleep(0.5)
    pages: Dict[str, str] = {}
    for i in range(0, len(titles), 20):
        data = api(prop="revisions", rvprop="content", rvslots="main",
                   titles="|".join(titles[i:i + 20]))
        for page in data["query"]["pages"].values():
            revisions = page.get("revisions")
            if revisions:
                pages[page["title"]] = revisions[0]["slots"]["main"]["*"]
        time.sleep(0.6)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(pages), encoding="utf-8")
    return pages


def flatten(text: str) -> str:
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    return re.sub(r"<[^>]+>", " ", text)


def armour_rows(pages: Dict[str, str]) -> List[dict]:
    """
    The `Name | Skill | Defense | Block Chance | Durability | Weight | Requirement` rows.

    These are wiki tables rather than prose, one row per piece, split on `|-`. Rows with
    fewer than six cells are headers or footers and are skipped.
    """
    out: List[dict] = []
    for text in pages.values():
        for block in re.split(r"\|-", flatten(text)):
            cells = [c.strip() for c in re.findall(r"^\|\s*(.*)$", block, re.M)]
            if len(cells) < 6 or not cells[0]:
                continue
            out.append({"name": cells[0], "defense": number(cells[2]),
                        "durability": number(cells[4]), "weight": number(cells[5])})
    return out


def number(text) -> Optional[float]:
    found = re.search(r"-?\d+(?:\.\d+)?", str(text or ""))
    return float(found.group()) if found else None


def parse_weapon(text: str) -> dict:
    out = {}
    found = re.search(r"Damage:\s*(\d+)\s*" + DASH + r"\s*(\d+)", text)
    if found:
        out["min"], out["max"] = int(found.group(1)), int(found.group(2))
    for key, pattern in (("weight", r"Weight:\s*([\d.]+)"),
                         ("speed", r"Attack Speed\s*\(([\d.]+)\)"),
                         ("durability", r"Durability:\s*(\d+)")):
        found = re.search(pattern, text)
        if found:
            out[key] = float(found.group(1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default=str(REPO_ROOT / "export_aegisfall"))
    ap.add_argument("--cache", default=str(REPO_ROOT / ".wikicache" / "weapons.json"))
    args = ap.parse_args()

    items = json.loads((Path(args.export) / "content" / "items.json")
                       .read_text(encoding="utf-8"))
    by_name = {}
    for row in items:
        if row.get("name"):
            by_name.setdefault(row["name"], row)

    print("fetching Category:Weapons (cache: " + args.cache + ")")
    pages = fetch_weapons(Path(args.cache))
    wiki = {title: parse_weapon(text) for title, text in pages.items()}
    matched = [(t, w, by_name[t]) for t, w in wiki.items() if t in by_name]
    print("wiki weapon pages: " + str(len(wiki)))
    print("names also in items.json: " + str(len(matched)) + "\n")

    def ours(row, field):
        if field in ("min", "max"):
            damage = row.get("damage") or []
            return damage[0].get(field) if damage else None
        if field == "speed":
            return (row.get("weapon") or {}).get("speed")
        return row.get(field)

    print(f"{'field':<12}{'compared':>9}{'exact':>7}{'differ':>8}   most common gap")
    # `durability` was parsed from the wiki from the day this file was written and never
    # appeared in this list, because `items.json` had no such column -- so it was read,
    # discarded, and silently counted zero times. Both halves are fixed now.
    for field in ("min", "max", "weight", "speed", "durability"):
        same = diff = 0
        gaps: Counter = Counter()
        for _t, w, row in matched:
            a, b = w.get(field), ours(row, field)
            if a is None or not isinstance(b, (int, float)):
                continue
            if abs(a - b) < 0.051:
                same += 1
            else:
                diff += 1
                gaps[round(a - b, 1)] += 1
        total = same + diff
        if total:
            top = ", ".join(f"{g:+g} x{c}" for g, c in gaps.most_common(3))
            print(f"{field:<12}{total:>9}{same:>7}{diff:>8}   {top}")

    # --- armour, which this check did not cover at all until items.json had a
    # defense rating to compare. `Category:Armor` is 35 pages of row tables.
    armour = armour_rows(fetch_category(Path(args.cache).with_name("armor.json"),
                                        "Category:Armor"))
    matched_armour = [(a, by_name[a["name"]]) for a in armour if a["name"] in by_name]
    print("\narmour rows on the wiki: " + str(len(armour)))
    print("names also in items.json: " + str(len(matched_armour)))
    print(f"\n{'field':<12}{'compared':>9}{'exact':>7}{'differ':>8}   most common gap")
    for label, wiki_key, our_key in (("defense", "defense", "defense_rating"),
                                     ("durability", "durability", "durability"),
                                     ("weight", "weight", "weight")):
        same = diff = 0
        gaps: Counter = Counter()
        for wiki_row, ours_row in matched_armour:
            a, b = wiki_row[wiki_key], ours_row.get(our_key)
            if a is None or not isinstance(b, (int, float)):
                continue
            if abs(a - b) < 0.051:
                same += 1
            else:
                diff += 1
                gaps[round(a - b, 1)] += 1
        if same + diff:
            top = ", ".join(f"{g:+g} x{c}" for g, c in gaps.most_common(3))
            print(f"{label:<12}{same+diff:>9}{same:>7}{diff:>8}   {top}")
    armours = sum(1 for r in items if r.get("type") == "ARMOR")
    rated = sum(1 for r in items if r.get("type") == "ARMOR" and r.get("defense_rating"))
    print("\nitems.json: " + str(armours) + " armour, " + str(rated)
          + " with a defense rating, " + str(armours - rated) + " without")
    if rated == 0:
        print("  !! every armour piece is missing its defense rating")

    empty = sum(1 for r in items if r.get("type") == "WEAPON" and not r.get("damage"))
    weapons = sum(1 for r in items if r.get("type") == "WEAPON")
    print("\nitems.json: " + str(weapons) + " weapons, " + str(weapons - empty)
          + " with damage, " + str(empty) + " without")
    if empty == weapons:
        print("  !! every weapon is missing damage -- the nested item_weapon read is broken")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
