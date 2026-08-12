#!/usr/bin/env python3
"""
Check `content/disciplines.json` against the Morloch wiki's discipline pages.

Why this exists
---------------
Sixth of the wiki comparisons, and the one that paid for the whole series. It found that
`export_content.py` was reading the requirement lists **without the `restrict` flag that
inverts them**, so on every rune that stores its requirement as an exclusion the export
said precisely the opposite of what the client does.

The flag sits next to the list in the same record:

    restrict False, list     the list is who MAY take it
    restrict True,  list     the list is who may NOT -- everyone else may
    restrict True,  empty    nothing is excluded, so anyone may

Measured with this checker against one parser, honouring the flag moves discipline races
from 41/171 to **171/171** and discipline classes from 175/214 to **214/214**. The blast
radius was much wider than disciplines: 619 items had their race list inverted, 56 their
class list, and 3,177 more shipped `[]` for "unrestricted", which reads exactly like
"nobody may".

Why the other checks did not catch it
-------------------------------------
`check_races_wiki.py` and `check_classes_wiki.py` score 12/12, 60/60, 60/60, 167/167 and
31/31, 99/99, 69/69 -- identically, on both the broken export and the fixed one. That is
not luck. 26 of the 27 CLASS runes store `restrict False`, so for classes the naive read
and the correct read agree; disciplines are where the inverted form is common. **Two
perfect scores were reported over a field that was backwards on 675 rows**, because
neither check covered the case that was wrong. A validation that only exercises the easy
majority passes for the wrong reason, and passing tells you less than it appears to.

Reading the score
-----------------
Every requirement now agrees, but three of the matches had to be taught to the comparison
rather than found by it, and each was a way the two sources say the same thing differently:

  * `Duelist` writes `all races` as prose where the filter expected the bare word `All`.
  * `Wyrmslayer` writes `Shades`, plural, against the cache's `Shade`.
  * `Skydancer` is one word on the wiki and `Sky Dancer` in the cache.
  * `Drannok` is the interesting one, and is resolved in `promotes_into` below. The wiki
    lists Warlock and Warrior; the cache says the requirement is base class **Fighter**
    plus race **Vampire**. Those are the same statement at different levels -- the classes
    promoting from Fighter that a Vampire may take are exactly `['Warlock', 'Warrior']`.
    The cache states the rule, the wiki enumerates what satisfies it.

So this one run produced both a real defect and four false alarms. The lesson is not that
low scores are usually noise, nor that they are usually real -- it is that the score is
not the finding. Read the disagreement.

    python tools/check_disciplines_wiki.py
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

from check_powers_wiki import api  # one fetch implementation for all of these

# Prose the wiki writes where it means "no restriction", against our `None`.
UNRESTRICTED = ("all", "all races", "all classes", "any", "none")


def fetch(cache: Path) -> Dict[str, str]:
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    titles, cont = [], None
    while True:
        kw = dict(list="categorymembers", cmtitle="Category:Disciplines", cmlimit="500")
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


def normalise(value: str) -> str:
    value = value.replace("Half Giant", "Half-Giant").strip(" '*")
    # `Shades` for `Shade`; the wiki pluralises some race names and not others.
    return value[:-1] if value.endswith("s") and value[:-1] in (
        "Shade", "Elf", "Dwarf", "Human", "Vampire", "Centaur", "Minotaur") else value


def bullet(text: str, label: str) -> List[str]:
    """The `*'''Races''': a, b, c` line, split and normalised."""
    found = re.search(r"\*'''%s'''*:\s*([^\n]*)" % label, text)
    if not found:
        return []
    parts = [normalise(p) for p in re.split(r"[,;]", found.group(1)) if p.strip()]
    return [p for p in parts if p.lower() not in UNRESTRICTED]


def promotes_into(classes: List[dict], name: str, required: Optional[set],
                  row: dict) -> bool:
    """
    Does class `name` satisfy a base-class requirement?

    `Drannok` requires base class Fighter and race Vampire; the wiki lists Warlock and
    Warrior. Both are Fighter promotions open to Vampires, so the two statements agree --
    the cache states the rule, the wiki enumerates what satisfies it.
    """
    if required is None:
        return True
    for entry in classes:
        if entry["name"] != name:
            continue
        if not set(entry.get("required_classes") or []) & required:
            return False
        races, open_to = row.get("eligible_races"), entry.get("eligible_races")
        return races is None or open_to is None or bool(set(open_to) & set(races))
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default=str(REPO_ROOT / "export_aegisfall"))
    ap.add_argument("--cache", default=str(REPO_ROOT / ".wikicache" / "disciplines.json"))
    args = ap.parse_args()

    rows = json.loads((Path(args.export) / "content" / "disciplines.json")
                      .read_text(encoding="utf-8"))
    # `Skydancer` on the wiki against `Sky Dancer` in the cache: match on the letters,
    # ignoring case as well as spacing, or that one page reports as missing.
    key = lambda name: name.replace(" ", "").casefold()
    ours = {key(r["name"]): r for r in rows}
    classes = json.loads((Path(args.export) / "content" / "classes.json")
                         .read_text(encoding="utf-8"))
    pages = fetch(Path(args.cache))
    print("Category:Disciplines members: " + str(len(pages)))
    print("disciplines.json rows: " + str(len(rows)))
    print("  name overlap: " + str(len(set(ours) & {key(t) for t in pages})) + "\n")

    tally: Counter = Counter()
    misses: List[str] = []
    print(f"{'discipline':<18}{'races':>10}{'classes':>10}")
    for title in sorted(pages):
        row = ours.get(key(title))
        if row is None:
            print(f"{title:<18}  not in disciplines.json")
            continue
        text = flatten(pages[title])
        line = f"{title:<18}"
        for label, field in (("Races", "eligible_races"),
                             ("Classes", "required_classes")):
            stated = bullet(text, label)
            # `None` is unrestricted, so every name the wiki lists is permitted.
            mine: Optional[set] = (set(row[field]) if row[field] is not None else None)
            agreed = [s for s in stated if mine is None or s in mine]
            rest = [s for s in stated if s not in agreed]
            # A requirement of "base class Fighter" is satisfied by the classes that
            # promote from Fighter, which is what the wiki lists instead. Resolve that
            # rather than call it a mismatch -- and count it apart so it stays visible.
            if rest and field == "required_classes":
                promoted = [s for s in rest if promotes_into(classes, s, mine, row)]
                tally["promotion"] += len(promoted)
                rest = [s for s in rest if s not in promoted]
                agreed += promoted
            tally[field] += len(agreed)
            tally[field + "_total"] += len(stated)
            misses += [f"{title} {label}: {s!r}" for s in rest]
            line += f"{len(agreed):>7}/{len(stated):<3}"
        print(line)

    print(f"\nraces {tally['eligible_races']}/{tally['eligible_races_total']}   "
          f"classes {tally['required_classes']}/{tally['required_classes_total']}"
          + (f"   ({tally['promotion']} matched through a base-class requirement rather "
             f"than by name)" if tally["promotion"] else ""))
    if misses:
        print("disagreements -- read each one; see this file's header for what the known "
              "ones turned out to be:")
        for m in misses[:10]:
            print("   " + m)
    else:
        print("every requirement agrees")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
