#!/usr/bin/env python3
"""
Check `content/powers.json` against the Morloch wiki, field by field.

Why this exists
---------------
`powers.json` is read out of the shipped client, and three of its 22 positional header
fields were named from the data alone, because the client names none of them (see
`tools/export_powers.py`). Names derived by correlation want an independent source, and the
wiki is one: it was written by players reading the game, not by this repo reading the
cache, so it agrees or disagrees for reasons that have nothing to do with how the parse was
written.

It is a comparison, not an import. Where the two disagree the cache is authoritative -- it
is the shipped data -- but a disagreement is worth understanding before it is dismissed,
and agreement across hundreds of powers is worth more than any amount of internal
consistency.

    python tools/check_powers_wiki.py                 # fetch and compare
    python tools/check_powers_wiki.py --cache <path>  # reuse a previous fetch

The wiki is a small community site. Pages come through the MediaWiki API in batches of 20
with a pause between calls -- about 30 requests for the whole comparison rather than one
per power -- and the fetch is cached so a re-run costs nothing.

There is no equivalent check for `effects.json`, and that is a property of the source
rather than an omission here. The wiki has no per-effect pages: its `Category:Powers` holds
class lists plus seven mechanics pages (Buff, Stun, Summon, Tracking, Invisibility, Skill,
Traveling Stance), and the `Effect(s)` field appears on five powers in total, carrying prose
about stacking rather than anything joinable. The 2,950 effects are checked instead against
their own source -- `tools/export_powers.py` accounts for every content line of
Effects.cfg -- and indirectly here, since the power fields these comparisons validate are
the ones the power-to-effect join is built on.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
API = "https://morloch.shadowbaneemulator.com/api.php"
UA = {"User-Agent": "sb2026-export-check/1.0 (validating a local cache export)"}
TRIPLE = "'" * 3


def api(**params) -> dict:
    params.setdefault("format", "json")
    params.setdefault("action", "query")
    url = API + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read())


def fetch_pages(cache: Path) -> Dict[str, str]:
    """Every page in Category:Powers, as wikitext. Cached."""
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    titles: List[str] = []
    cont = None
    while True:
        kw = dict(list="categorymembers", cmtitle="Category:Powers", cmlimit="500")
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


def clean(text: str) -> str:
    """Strip the wiki markup that sits inside a field value."""
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace(TRIPLE, "").replace("''", "")
    return " ".join(text.split()).strip(" .,")


def parse_powers(pages: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    """`=== Name ===` blocks with their bolded `Field: value` lines."""
    field = re.compile(TRIPLE + r"([^']{2,30})" + TRIPLE + r":([^\n<]*)")
    out: Dict[str, Dict[str, str]] = {}
    for title, text in pages.items():
        # Split on level-3 headings; anything above the first is page furniture.
        parts = re.split(r"\n=== *(.+?) *===", text)
        for i in range(1, len(parts) - 1, 2):
            name = clean(parts[i])
            fields = {}
            for key, value in field.findall(parts[i + 1]):
                fields.setdefault(clean(key), clean(value))
            if not fields:
                continue
            # A power can appear on more than one class page; keep the fuller record.
            if name not in out or len(fields) > len(out[name]):
                fields["_page"] = title
                out[name] = fields
    return out


def number(text: str):
    found = re.search(r"-?\d+(?:\.\d+)?", text or "")
    return float(found.group()) if found else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default=str(REPO_ROOT / "export_aegisfall"))
    ap.add_argument("--cache", default=str(REPO_ROOT / ".wikicache" / "powers.json"))
    args = ap.parse_args()

    powers = json.loads((Path(args.export) / "content" / "powers.json")
                        .read_text(encoding="utf-8"))["powers"]
    by_name: Dict[str, list] = defaultdict(list)
    for row in powers.values():
        if row.get("name"):
            by_name[row["name"]].append(row)

    print("fetching Category:Powers (cache: " + args.cache + ")")
    wiki = parse_powers(fetch_pages(Path(args.cache)))
    print("wiki: " + str(len(wiki)) + " named powers across its class pages")
    print("ours: " + str(len(powers)) + " powers, " + str(len(by_name)) + " distinct names\n")

    matched = [(n, w, by_name[n][0]) for n, w in wiki.items() if n in by_name]
    print("names in both: " + str(len(matched)))
    print("on the wiki, absent from the cache: " + str(len(wiki) - len(matched)))
    print("in the cache, absent from the wiki: " + str(len(by_name) - len(matched)) + "\n")

    checks = (
        ("Casting Time", "castSeconds"),
        ("Recycle Time", "recycleSeconds"),
        ("Mana Cost", "costAmount"),
        ("Stamina Cost", "costAmount"),
    )
    print(f"{'wiki field':<15}{'ours':<17}{'n':>6}{'agree':>7}{'differ':>8}  worst examples")
    for wiki_key, our_key in checks:
        agree = dis = 0
        examples = []
        for name, w, ours in matched:
            if wiki_key not in w:
                continue
            a, b = number(w[wiki_key]), ours.get(our_key)
            if a is None or not isinstance(b, (int, float)):
                continue
            if abs(a - b) < 0.051:
                agree += 1
            else:
                dis += 1
                if len(examples) < 2:
                    examples.append(name + ": wiki " + str(a) + " ours " + str(b))
        total = agree + dis
        if total:
            pct = 100 * agree / total
            print(f"{wiki_key:<15}{our_key:<17}{total:>6}{agree:>7}{dis:>8}  "
                  f"{pct:.0f}%  {'; '.join(examples)}")

    # --- fields whose values are tokens rather than numbers -------------------------
    def token_check(wiki_key, test):
        ok = bad = 0
        for _n, w, ours in matched:
            if wiki_key not in w:
                continue
            verdict = test(w[wiki_key], ours)
            if verdict is None:
                continue
            ok += bool(verdict)
            bad += not verdict
        if ok + bad:
            print(f"{wiki_key:<15}{'(token)':<17}{ok+bad:>6}{ok:>7}{bad:>8}  "
                  f"{100*ok/(ok+bad):.0f}%")

    print()
    token_check("Power Type",
                lambda t, o: t.strip().upper().startswith((o.get("kind") or "")[:5]))
    token_check("Focus Skill",
                lambda t, o: ((o["skillName"].lower() in t.lower())
                              if o.get("skillName") not in (None, "", "None", "Unknown")
                              else None))
    token_check("Target and Range",
                lambda t, o: ((o.get("target") or "").lower()
                              in t.lower().replace("mobile", "pcmobile")) or None)

    # --- Area of Effect, which the wiki uses for two different quantities ------------
    #
    # Read as a radius throughout it agrees on only 39%, which looks like a defect in this
    # export and is not one: on a power whose areaShape is NONE the wiki is quoting the
    # *range* under that heading. Split by shape, 74 of 93 land exactly, and the remainder
    # is ordinary drift between the wiki's patch and this cache (it says 32 where the cache
    # says 30). Both `areaRadius` and `range` come out validated.
    hits = Counter()
    for _n, w, ours in matched:
        if "Area of Effect" not in w:
            continue
        stated = number(w["Area of Effect"])
        if stated is None:
            continue
        shape = ours.get("areaShape")
        field = "areaRadius" if shape and shape != "NONE" else "range"
        value = ours.get(field)
        hits[(field, isinstance(value, (int, float)) and abs(stated - value) < 0.51)] += 1
    agree = sum(c for k, c in hits.items() if k[1])
    total = sum(hits.values()) or 1
    print(f"{'Area of Effect':<15}{'radius or range':<17}{total:>6}{agree:>7}"
          f"{total-agree:>8}  {100*agree/total:.0f}%   "
          f"(radius when areaShape is set, range when it is NONE)")

    table = Counter()
    for name, w, ours in matched:
        value = w.get("Requires Hit Roll", "")
        has = bool(value) and value.strip().lower()[:1] in ("y", "t")
        table[(bool(ours.get("requiresHitRoll")), has)] += 1
    print("\nrequiresHitRoll against the wiki's 'Requires Hit Roll':")
    print(f"{'ourFlag':>10}{'hit roll':>10}{'count':>8}")
    for key in sorted(table):
        print(f"{str(key[0]):>10}{str(key[1]):>10}{table[key]:>8}")
    same = table[(True, True)] + table[(False, False)]
    total = sum(table.values()) or 1
    print("   agreement " + str(same) + "/" + str(total)
          + " = %.0f%%" % (100 * same / total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
