#!/usr/bin/env python3
"""
Check `content/classes.json` against the Morloch wiki's twenty-six class pages.

Why this exists
---------------
Fifth of the wiki comparisons, and the second to find nothing wrong. Every field agrees:
31 base-class links, 99 eligible races, 69 granted skills, all exact.

It is not a restatement of `check_races_wiki.py`. That one validates race -> class (167/167
from the race pages); this validates class -> race (99/99 from the class pages). Those are
the same relation read from opposite ends, and agreeing from both is a stronger statement
than either alone.

`Category:Class` holds 26 class pages, and `classes.json` carries those 26 plus `Pet`, which
is a rune type rather than a player class -- so the extra row is expected rather than a
discrepancy.

Three parsing traps, all of which cost a false alarm before being handled here
-----------------------------------------------------------------------------
  * The stats are in an infobox as `Row N title` / `Row N info` pairs, not prose.
  * `Half Giant` on the wiki against `Half-Giant` in the cache, and `''all races''` written
    where Fighter and Warrior would otherwise list twelve. Five apparent race mismatches,
    none real.
  * **`Wear Armor, Medium` is one skill whose name contains a comma.** Splitting the wiki's
    comma-separated skill list breaks it into `Wear Armor` and `Medium`, neither of which
    matches anything, and reported 64/74 until the name was protected. The cache had it
    right the whole time.

That last one is the third occasion in this repo where a low agreement score was the
comparison misreading the wiki rather than the export being wrong -- `Area of Effect` and
the race attribute links were the others. Read a disagreement before reporting it.

    python tools/check_classes_wiki.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_powers_wiki import api  # one fetch implementation for all of these

NAMES = ["Assassin", "Barbarian", "Bard", "Channeler", "Confessor", "Crusader", "Doomsayer",
         "Druid", "Fighter", "Fury", "Healer", "Huntress", "Mage", "Necromancer",
         "Nightstalker", "Prelate", "Priest", "Ranger", "Rogue", "Scout", "Sentinel",
         "Templar", "Thief", "Warlock", "Warrior", "Wizard"]
# Skill names that contain the separator the wiki lists them with.
COMMA_SKILLS = ("Wear Armor, Medium", "Wear Armor, Heavy", "Wear Armor, Light")


def fetch(cache: Path) -> Dict[str, str]:
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    pages: Dict[str, str] = {}
    for i in range(0, len(NAMES), 20):
        data = api(prop="revisions", rvprop="content", rvslots="main",
                   titles="|".join(NAMES[i:i + 20]))
        for page in data["query"]["pages"].values():
            revisions = page.get("revisions")
            if revisions:
                pages[page["title"]] = revisions[0]["slots"]["main"]["*"]
        time.sleep(0.6)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(pages), encoding="utf-8")
    return pages


def infobox(text: str) -> Dict[str, str]:
    """The `Row N title` / `Row N info` pairs, links and tags flattened."""
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    out = {}
    for m in re.finditer(r"Row (\d+) title\s*=\s*([^\n|]*)\|?\s*\|?Row \1 info\s*=\s*([^\n|]*)",
                         text):
        out[m.group(2).strip()] = m.group(3).strip()
    return out


def normalise(value: str) -> str:
    return value.replace("Half Giant", "Half-Giant").strip(" '")


def split_plain(value: str) -> List[str]:
    return [normalise(x) for x in re.split(r"[,;]", value or "") if x.strip()]


def split_skills(value: str) -> List[str]:
    value = re.sub(r"\(level \d+\)", ",", value or "")
    guards = {name: chr(1 + i) for i, name in enumerate(COMMA_SKILLS)}
    for name, token in guards.items():
        value = value.replace(name, token)
    back = {token: name for name, token in guards.items()}
    return [back.get(part, part) for part in split_plain(value)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default=str(REPO_ROOT / "export_aegisfall"))
    ap.add_argument("--cache", default=str(REPO_ROOT / ".wikicache" / "classes.json"))
    args = ap.parse_args()

    classes = {c["name"]: c for c in json.loads(
        (Path(args.export) / "content" / "classes.json").read_text(encoding="utf-8"))}
    pages = fetch(Path(args.cache))
    extra = sorted(set(classes) - set(pages))
    print("wiki class pages: " + str(len(pages)))
    print("classes.json rows: " + str(len(classes)) + "  (extra: " + str(extra) + ")\n")

    tally = Counter()
    misses: List[str] = []
    print(f"{'class':<14}{'races':>10}{'baseClass':>12}{'skills':>9}")
    for title in sorted(pages):
        ours = classes.get(title)
        if ours is None:
            print(f"{title:<14}  not in classes.json")
            continue
        box = infobox(pages[title])
        # `''all races''` stands in for the full list on Fighter and Warrior.
        races = [r for r in split_plain(box.get("Races")) if "all races" not in r]
        mine = {normalise(r) for r in (ours.get("eligible_races") or [])}
        base = split_plain(box.get("Base Classes"))
        mine_base = set(ours.get("required_classes") or [])
        skills = split_skills(box.get("Skills Granted"))
        mine_skills = {g.get("skill") for g in (ours.get("skill_grants") or [])}

        for label, wiki_values, ours_values in (("race", races, mine),
                                                ("base", base, mine_base),
                                                ("skill", skills, mine_skills)):
            hit = sum(1 for v in wiki_values if v in ours_values)
            tally[label] += hit
            tally[label + "_total"] += len(wiki_values)
            misses += [f"{title} {label}: {v!r}" for v in wiki_values if v not in ours_values]
        print(f"{title:<14}{sum(1 for r in races if r in mine):>6}/{len(races):<3}"
              f"{sum(1 for b in base if b in mine_base):>8}/{len(base):<3}"
              f"{sum(1 for s in skills if s in mine_skills):>6}/{len(skills)}")

    print(f"\nraces {tally['race']}/{tally['race_total']}   "
          f"base classes {tally['base']}/{tally['base_total']}   "
          f"skills {tally['skill']}/{tally['skill_total']}")
    if misses:
        print("disagreements -- read them before assuming the cache is wrong; every one so "
              "far has been this parser's fault:")
        for m in misses[:10]:
            print("   " + m)
    else:
        print("every field agrees")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
