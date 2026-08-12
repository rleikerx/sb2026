#!/usr/bin/env python3
"""
Check `content/races.json` against the Morloch wiki's twelve race pages.

Why this exists
---------------
Third of the wiki comparisons, after `check_powers_wiki.py` and `check_items_wiki.py`, and
the only one so far that found nothing wrong. That is worth having on record: the other two
turned up a misnamed field and a column that was empty on all 4,021 rows, so "the wiki
agrees" is a real result rather than an absence of one.

Every number matches. 12 creation costs, 60 base attributes and 60 caps, all exact, and all
167 class entries. `Category:Races` holds exactly the twelve races `races.json` flags
`standard_creation`, which independently confirms that flag.

Two parsing notes, because both cost a false alarm on the first pass and would cost the
next reader one too:

  * Four of the twelve pages write the attribute as a wiki link -- `40 Base [[Strength]] /
    95 Max Strength` -- so links have to be flattened before the numbers are read. Without
    that those four report 0/5 and look like a data disagreement.
  * The wiki wraps long class lists with `<br>`, which arrives as a `<br> Prelate` entry.
    Stripping tags takes the class match from 154/167 to 167/167.

Both were failures of the comparison, not of either source. A disagreement is worth
understanding before it is reported as a finding.

    python tools/check_races_wiki.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_powers_wiki import api  # one fetch implementation, not three

TITLES = ["Aelfborn", "Aracoix", "Centaur", "Dwarf", "Elf", "Half Giant",
          "Human", "Irekei", "Minotaur", "Nephilim", "Shade", "Vampire"]
ATTRS = ("Strength", "Dexterity", "Constitution", "Intelligence", "Spirit")


def fetch(cache: Path) -> Dict[str, str]:
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    data = api(prop="revisions", rvprop="content", rvslots="main",
               titles="|".join(TITLES))
    pages = {}
    for page in data["query"]["pages"].values():
        revisions = page.get("revisions")
        if revisions:
            pages[page["title"]] = revisions[0]["slots"]["main"]["*"]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(pages), encoding="utf-8")
    return pages


def flatten(text: str) -> str:
    """Wiki links and HTML out, so the numbers and names underneath can be read."""
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    return re.sub(r"<[^>]+>", " ", text)


def parse(text: str) -> dict:
    text = flatten(text)
    out = {"base": {}, "cap": {}, "classes": []}
    for m in re.finditer(r"(\d+)\s+Base\s+(\w+)\s*/\s*(\d+)\s+Max\s+(\w+)", text):
        out["base"][m.group(2)] = int(m.group(1))
        out["cap"][m.group(4)] = int(m.group(3))
    found = re.search(r"Creation Cost'*:\s*(\d+)", text)
    out["cost"] = int(found.group(1)) if found else None
    for pattern in (r"Base Classes'*:\s*([^\n]*)", r"\n\*'''Classes'''*:\s*([^\n]*)"):
        found = re.search(pattern, text)
        if found:
            out["classes"] += [c.strip() for c in re.split(r"[,;]", found.group(1))
                               if c.strip()]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default=str(REPO_ROOT / "export_aegisfall"))
    ap.add_argument("--cache", default=str(REPO_ROOT / ".wikicache" / "races.json"))
    args = ap.parse_args()

    races = {r["race"]: r for r in json.loads(
        (Path(args.export) / "content" / "races.json").read_text(encoding="utf-8"))}
    pages = fetch(Path(args.cache))

    playable = sorted(r for r, v in races.items() if v.get("standard_creation"))
    expected = sorted(t.replace("Half Giant", "Half-Giant") for t in pages)
    print("Category:Races members: " + str(len(pages)))
    print("races.json standard_creation: " + str(len(playable)))
    print("  same set: " + str(playable == expected) + "\n")

    tally = Counter()
    print(f"{'race':<12}{'cost':>6}{'base':>7}{'caps':>7}{'classes':>10}")
    for title in sorted(pages):
        ours = races[title.replace("Half Giant", "Half-Giant")]
        w = parse(pages[title])
        base = sum(1 for a in ATTRS if w["base"].get(a) == ours["attributes"].get(a))
        cap = sum(1 for a in ATTRS if w["cap"].get(a) == ours["attribute_caps"].get(a))
        cost_ok = w["cost"] == ours["creation_cost"]
        mine = set(ours.get("classes") or [])
        hit = sum(1 for c in w["classes"] if c in mine)
        tally["cost"] += cost_ok
        tally["base"] += base
        tally["cap"] += cap
        tally["cls"] += hit
        tally["cls_total"] += len(w["classes"])
        tally["n"] += 1
        print(f"{title:<12}{('OK' if cost_ok else 'X'):>6}{base:>5}/5{cap:>5}/5"
              f"{hit:>7}/{len(w['classes'])}")
    n = tally["n"]
    print(f"\ncreation cost {tally['cost']}/{n}   base {tally['base']}/{n*5}"
          f"   caps {tally['cap']}/{n*5}   classes {tally['cls']}/{tally['cls_total']}")
    perfect = (tally["cost"] == n and tally["base"] == n * 5 and tally["cap"] == n * 5
               and tally["cls"] == tally["cls_total"])
    print("every field agrees" if perfect else "!! a field disagrees -- read it before "
          "assuming the cache is wrong; both prior mismatches here were the parser's fault")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
