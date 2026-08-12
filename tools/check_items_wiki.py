#!/usr/bin/env python3
"""
Check `content/items.json` against the Morloch wiki's weapon pages.

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

    python tools/check_items_wiki.py

Fetches Category:Weapons through the MediaWiki API in batches of 20 with a pause between
calls, and caches under `.wikicache/` so a re-run costs nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict

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
    for field in ("min", "max", "weight", "speed"):
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

    empty = sum(1 for r in items if r.get("type") == "WEAPON" and not r.get("damage"))
    weapons = sum(1 for r in items if r.get("type") == "WEAPON")
    print("\nitems.json: " + str(weapons) + " weapons, " + str(weapons - empty)
          + " with damage, " + str(empty) + " without")
    if empty == weapons:
        print("  !! every weapon is missing damage -- the nested item_weapon read is broken")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
