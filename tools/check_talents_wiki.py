#!/usr/bin/env python3
"""
Check `content/talents.json` against the Morloch wiki's `Starting Traits` and
`Statistic Rune` pages.

Why this exists
---------------
Seventh of the wiki comparisons, and the second to find whole columns *missing* rather than
wrong. The wiki documents things about a talent that `export_content.py` was not exporting
at all, every one of them sitting in the cache the whole time:

    wiki field              cache field                          rows
    Requires <Attr> of      item_attr_req                        62 talents
    Rune Category           rune_sub_type                        202 talents
    Applies Effect(s)       item_user_power_action               46 talents
    -- no wiki field --     item_power_grant                     97 talents
    -- no wiki field --     rune_is_standard_character_creation  92 talents
    -- no wiki field --     rune_rank                            47 talents

That last group has no wiki field and is why the file was hard to use: nothing in
`talents.json` said **which of the 240 rows a player may actually pick**. 92 are flagged
for character creation; the other 148 are NPC runes -- `Archer Mob`, `Belgosch Lord`,
`Aelfborn Trainer` -- sitting in the same table. A consumer building a creation screen had
no way to separate them, and the wiki documenting exactly 85 is what made the gap visible.

Two pages, two populations
--------------------------
`Starting Traits` covers the 85 player traits as a field table. `Statistic Rune` covers the
drop-found stat runes as a ladder -- Enhanced +5 at prerequisite 85 through of the Gods +40
at 120 -- which is a different 35 rows of the same file, and the only source for them.

Five talent names are not unique
--------------------------------
`Proficient with Axes`, `Proficient with Daggers`, `Proficient with Hammers`,
`Witch Sight` and `Wizard's Apprentice` each exist **twice**, under different `asset_id`s
with different data. In every case the wiki matches the lower id and the higher one is a
stripped duplicate -- `Proficient with Daggers` 250083 requires Healer where 250125
requires nothing. Keying this file by name silently keeps whichever row is read last, which
is what this checker did on its first run, and it reported `Wizard's Apprentice` as four
separate disagreements. **Key `talents.json` by `asset_id`.** Every name here is compared
against all candidates and counted as agreeing if any of them matches.

Reading the effect comparison
-----------------------------
Two things make effects harder to compare than the rest, and both are properties of the
shipped data rather than of this export.

`applies_effects` names a **power action**, not an effect. Most action ids happen to equal
the effect they apply, so 212 of the 231 rune tokens are found in `effects.json` directly
-- but 19 are not, and `TRT-TIRELESS` applying `TIRELESS` was unreachable until
`export_powers.py` began emitting its whole action table. It now resolves 231/231.

And 194 effects carry a placeholder in the display-name slot: `MOVE-B-5% "MOB" 0` and
`RES-MAGIC-B-5 "TALENT" 0` are what `Effects.cfg` literally contains. So an effect's
meaning has to be read from its `mods`, and this matches on shared vocabulary across name,
mod names and mod arguments rather than on string equality. That is a weaker test than the
others here and is listed separately for that reason.

The score
---------
407 of 408. Nine of the eleven fields agree exactly and completely, including all 35 stat
runes on both prerequisite and increase, and all 23 race requirements -- which is a second
independent confirmation of the `restrict` flag that
`tools/check_disciplines_wiki.py` found.

The one difference is real and one-sided: the wiki gives `Blood of the Dragon` both Fire
Resistance and `Movement Speed: + 5%`, and the record carries a single action,
`RES-FIRE-B-5`. Checked against the raw COBJECT rather than the export -- nothing is being
dropped, the second effect is not there. The cache is authoritative; the wiki is
describing a different build or is simply wrong.

Parsing notes, each of which cost a false alarm first
-----------------------------------------------------
  * `'''Required Race: '''Irekei` puts the space and colon *inside* the bold.
  * Several fields share one line, so a value runs to the next `'''`, not to the newline.
  * `Granted: 5 Base Con/ 10 Max Con` abbreviates three of the five attributes.
  * Base and max differ more often than not, so they are two comparisons rather than one.
  * `+5 to Staff skill` is an *adjustment* (`rune_skill_adj`), not a grant. Brawler both
    grants Unarmed Combat and adjusts it by +10; reading the wiki's number against the
    grant compares 10 against 1 and reported 0/27.
  * `Medium Armor` on the wiki is the skill `Wear Armor, Medium` -- the same comma-in-a-
    skill-name trap that `check_classes_wiki.py` documents.

    python tools/check_talents_wiki.py
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

TITLES = "Starting Traits|Statistic Rune"
ATTRS = ("Strength", "Dexterity", "Constitution", "Intelligence", "Spirit")
# The wiki abbreviates inside `Granted:` lines but not in `Requires ... of:` labels.
ABBREV = {"Str": "Strength", "Dex": "Dexterity", "Con": "Constitution",
          "Int": "Intelligence", "Spi": "Spirit"}
# Wiki spellings that differ from the cache by more than case or spacing.
ALIAS = {"Scion of the Dar Khelegur": "Scion of the Dar Khelegeur"}
# The wiki writes the stat-rune categories as prose; the cache uses a token.
CATEGORY_ALIAS = {"Increase Maximum %s" % a: "%sMaxIncrease" % a[:3] for a in ATTRS}
# Skill names the wiki shortens. The cache spelling is the real one.
SKILL_ALIAS = {"Light Armor": "Wear Armor, Light", "Medium Armor": "Wear Armor, Medium",
               "Heavy Armor": "Wear Armor, Heavy"}
# Words that carry no distinguishing meaning when matching an effect label.
FILLER = {"rate", "bonus", "of", "the", "to", "a", "an", "and", "point", "points",
          "this", "entity", "can", "in", "both", "is", "increased", "increase"}
# The client's mod names against the wiki's wording for the same quantity. `DCV` and
# `OCV` are defensive and offensive combat value -- what the wiki calls Defense and
# Attack Bonus -- and `MOVE-B-5%` modifies `Speed` where the wiki says movement.
SYNONYM = {"movement": "speed", "move": "speed", "moving": "speed",
           "dcv": "defense", "ocv": "attack"}


def fetch(cache: Path) -> Dict[str, str]:
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    data = api(prop="revisions", rvprop="content", rvslots="main", titles=TITLES)
    pages = {p["title"]: p["revisions"][0]["slots"]["main"]["*"]
             for p in data["query"]["pages"].values() if p.get("revisions")}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(pages), encoding="utf-8")
    return pages


def flatten(text: str) -> str:
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    return re.sub(r"<[^>]+>", " ", text)


def field(text: str, label: str) -> Optional[str]:
    """One `'''Label:''' value`, ending at the next bold label rather than the newline."""
    found = re.search(r"'''%s\s*:?\s*'''\s*:?\s*([^\n]*)" % re.escape(label), text)
    return found.group(1).split("'''")[0].strip() if found else None


def names(value: Optional[str]) -> List[str]:
    out = []
    for part in re.split(r"[,;]", value or ""):
        part = part.strip(" '*:")
        if part and part.lower() not in ("all", "none", "any"):
            out.append(part.replace("Half Giant", "Half-Giant"))
    return out


def granted(text: str) -> Dict[str, Dict[str, int]]:
    """`Granted: 10 Base Strength/ 10 Max Strength` -> base and max deltas."""
    out: Dict[str, Dict[str, int]] = {"base": {}, "max": {}}
    for value in re.findall(r"'''Granted:?\s*'''\s*:?\s*([^\n]*)", text):
        for amount, which, attr in re.findall(
                r"([+-]?\d+)\s+(Base|Max)\s+([A-Za-z]+)", value):
            attr = ABBREV.get(attr, attr)
            if attr in ATTRS:
                out["base" if which == "Base" else "max"][attr] = int(amount)
    return out


def granted_skills(text: str) -> Dict[str, int]:
    """
    The skill *bonus*, from either spelling the wiki uses.

    `+5 to Staff skill` and `granted skill Unarmed Combat (+ 10 point bonus)` are both
    adjustments -- `rune_skill_adj` in the cache -- and are a different thing from
    `rune_skill_grant`, which confers the skill and carries no magnitude.
    """
    out: Dict[str, int] = {}
    for amount, skill in re.findall(r"([+-]?\d+)\s+to\s+([A-Za-z' ]+?)\s+skill", text):
        out[SKILL_ALIAS.get(skill.strip(), skill.strip())] = int(amount)
    for skill, amount in re.findall(
            r"granted skill\s+'''([^']+)'''\s*\(\s*\+?\s*(\d+)", text):
        out[SKILL_ALIAS.get(skill.strip(), skill.strip())] = int(amount)
    return out


def granted_skill_names(text: str) -> List[str]:
    """`granted skill '''Unarmed Combat'''` -- the grant, not the adjustment."""
    return [SKILL_ALIAS.get(s.strip(), s.strip())
            for s in re.findall(r"granted skill\s+'''([^']+)'''", text)]


def our_adjustments(row: dict) -> Dict[str, int]:
    """`skill_adjustments` flattened to {skill: first adjustment}."""
    out: Dict[str, int] = {}
    for entry in row.get("skill_adjustments") or []:
        pairs = entry.get("adjustments") or []
        if pairs and pairs[0]:
            out[entry["skill"]] = pairs[0][0]
    return out


def applied_effects(text: str) -> List[str]:
    """The `**Fire Resistance: + 10` bullets under `Applies Effect(s)`."""
    block = re.search(r"Applies Effect\(s\):?\s*'''((?:\s*\*\*[^\n]*\n?)+)", text)
    if not block:
        return []
    return [line.strip(" *").split(":")[0].strip()
            for line in block.group(1).splitlines() if line.strip().startswith("**")]


def words(text: str) -> set:
    """Distinctive lowercase words, with `SeeInvisible` split into its two."""
    out = set()
    for token in re.findall(r"[A-Za-z]+", text or ""):
        for word in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+", token):
            word = word.lower()
            if word not in FILLER:
                out.add(SYNONYM.get(word, word))
    return out


def effect_vocabulary(entry: dict) -> set:
    """
    Everything an effect says about itself: its name plus its mods.

    194 effects carry a placeholder name (`"MOB"`, `"TALENT"`) because that is what
    `Effects.cfg` ships, so the name alone is not enough to recognise one.
    """
    out = words(entry.get("name") or "")
    for mod in entry.get("mods") or []:
        out |= words(mod.get("name") or "")
        for arg in mod.get("args") or []:
            if isinstance(arg, str):
                out |= words(arg)
    return out


def resolve(token: str, effects: Dict[str, dict], actions: Dict[str, dict]) -> List[dict]:
    """
    A rune's `applies_effects` token to the effect records it ends at.

    The token names a *power action*, not an effect. Most action ids happen to equal the
    effect they apply, which is why 212 of the 231 rune tokens are found in `effects.json`
    directly -- but 19 are not: `TRT-TIRELESS` applies `TIRELESS`. Going through the
    action table takes the join to 231/231.
    """
    if token in effects:
        return [effects[token]]
    named = (actions.get(token) or {}).get("effects") or []
    return [effects[e] for e in named if e in effects]


def check_traits(text: str, ours: Dict[str, List[dict]], effects: Dict[str, dict],
                 actions: Dict[str, dict], races: List[str], classes: List[str],
                 tally: Counter, misses: List[str]) -> int:
    parts = re.split(r"\n=== *(.+?) *===", text)
    seen = 0
    for i in range(1, len(parts) - 1, 2):
        title = flatten(parts[i]).strip()
        body = flatten(parts[i + 1])
        rows = ours.get(ALIAS.get(title, title))
        if not rows:
            misses.append(f"{title}: no such talent")
            continue
        seen += 1

        def compare(label: str, wiki_value, read) -> None:
            """Agree if *any* row of a duplicated name matches."""
            if wiki_value in (None, {}, [], set()):
                return
            tally[label + "_total"] += 1
            if any(wiki_value == read(row) for row in rows):
                tally[label] += 1
            else:
                misses.append(f"{title} {label}: wiki {wiki_value!r} "
                              f"ours {[read(row) for row in rows]!r}")

        cost = field(body, "Creation Cost")
        compare("cost", int(cost) if cost and cost.isdigit() else None,
                lambda r: r.get("creation_cost"))
        category = field(body, "Rune Category")
        compare("category", CATEGORY_ALIAS.get(category, category),
                lambda r: r.get("rune_category"))

        want = {a: int(v) for a in ATTRS
                for v in [field(body, "Requires %s of" % a)] if v and v.isdigit()}
        compare("attrreq", want or None, lambda r: r.get("attribute_requirements") or None)

        grants = granted(body)
        compare("base", grants["base"] or None, lambda r: r.get("attributes") or None)
        compare("cap", grants["max"] or None, lambda r: r.get("attribute_caps") or None)

        compare("skill", granted_skills(body) or None, our_adjustments)
        compare("grant", set(granted_skill_names(body)) or None,
                lambda r: {g["skill"] for g in r.get("skill_grants") or []})

        for label, single, plural, key, universe in (
                ("race", "Race", "Races", "eligible_races", races),
                ("class", "Class", "Classes", "required_classes", classes)):
            required = (names(field(body, "Required " + single))
                        or names(field(body, "Required " + plural)))
            prohibited = (names(field(body, "Prohibited " + single))
                          or names(field(body, "Prohibited " + plural)))
            if required:
                allow = set(required)
            elif prohibited:
                allow = {u for u in universe if u not in set(prohibited)}
            else:
                allow = None
            compare(label, allow,
                    lambda r, k=key: set(r[k]) if r.get(k) is not None else None)

        # Effects are matched on shared vocabulary rather than equality, because the wiki
        # writes a label ("Defense Bonus") where the cache carries a mod name ("DCV") and
        # sometimes writes a whole sentence. Weaker than the checks above, and reported
        # separately for that reason: it says our effect is plausibly the wiki's, not that
        # the two strings agree.
        for stated in applied_effects(body):
            tally["effect_total"] += 1
            want_words = words(stated) | words(title)
            matched = any(
                want_words & effect_vocabulary(entry)
                for row in rows
                for token in row.get("applies_effects") or []
                for entry in resolve(token["effect"], effects, actions))
            if matched:
                tally["effect"] += 1
            else:
                have = sorted({token["effect"] for row in rows
                               for token in row.get("applies_effects") or []})
                misses.append(f"{title} effect: wiki {stated!r} ours {have}")
    return seen


def check_stat_runes(text: str, rows: List[dict], tally: Counter,
                     misses: List[str]) -> int:
    """The `Statistic Rune` ladder: prerequisite and increase per size."""
    ladder = {}
    for size, gain, prereq in re.findall(
            r"!\s*([A-Za-z' ]+?)\s*\(\+(\d+)\)\s*\n\|\s*(\d+)", text):
        ladder[size.strip()] = (int(gain), int(prereq))
    if not ladder:
        return 0
    by_name = {r["name"]: r for r in rows}
    seen = 0
    for size, (gain, prereq) in sorted(ladder.items()):
        for attr in ATTRS:
            row = by_name.get(f"{size} {attr}")
            if row is None:
                continue
            seen += 1
            for label, want, got in (
                    ("stat_cap", gain, row.get("attribute_caps", {}).get(attr)),
                    ("stat_req", prereq,
                     row.get("attribute_requirements", {}).get(attr))):
                tally[label + "_total"] += 1
                if want == got:
                    tally[label] += 1
                else:
                    misses.append(f"{size} {attr} {label}: wiki {want} ours {got}")
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default=str(REPO_ROOT / "export_aegisfall"))
    ap.add_argument("--cache", default=str(REPO_ROOT / ".wikicache" / "talents.json"))
    args = ap.parse_args()

    content = Path(args.export) / "content"
    rows = json.loads((content / "talents.json").read_text(encoding="utf-8"))
    # Five names are not unique, so this maps to every candidate rather than the last.
    ours: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        ours[row["name"]].append(row)
    effects = json.loads((content / "effects.json").read_text(encoding="utf-8"))
    effects = effects.get("effects", effects)  # the file wraps them in a header
    # The action table is how a rune token reaches an effect it does not share a name with.
    actions = json.loads((content / "powers.json").read_text(encoding="utf-8"))
    actions = actions.get("actions", {})
    races = [r["race"] for r in json.loads((content / "races.json")
                                           .read_text(encoding="utf-8"))
             if r.get("standard_creation")]
    classes = [c["name"] for c in json.loads((content / "classes.json")
                                             .read_text(encoding="utf-8"))
               if c["name"] != "Pet"]

    pages = fetch(Path(args.cache))
    tally: Counter = Counter()
    misses: List[str] = []
    traits = check_traits(pages.get("Starting Traits", ""), ours, effects, actions,
                          races, classes, tally, misses)
    stat = check_stat_runes(pages.get("Statistic Rune", ""), rows, tally, misses)

    selectable = sum(1 for r in rows if r.get("standard_creation"))
    duplicated = sorted(n for n, v in ours.items() if len(v) > 1)
    print("talents.json rows: " + str(len(rows)) + "  (" + str(selectable)
          + " player-selectable, " + str(len(rows) - selectable) + " NPC runes)")
    print("names carrying more than one row: " + str(duplicated))
    print("Starting Traits sections matched: " + str(traits))
    print("Statistic Rune ladder entries matched: " + str(stat) + "\n")

    labels = (("cost", "Creation Cost"), ("category", "Rune Category"),
              ("attrreq", "Requires <Attr> of"), ("base", "Granted, base"),
              ("cap", "Granted, max"), ("skill", "skill adjustment"),
              ("grant", "granted skill"),
              ("race", "Required/Prohibited Race"),
              ("class", "Required/Prohibited Class"),
              ("effect", "Applies Effect(s)"),
              ("stat_cap", "stat rune increase"), ("stat_req", "stat rune prerequisite"))
    print(f"{'wiki field':<28}{'compared':>9}{'agree':>7}{'differ':>8}")
    for key, label in labels:
        total = tally[key + "_total"]
        if total:
            print(f"{label:<28}{total:>9}{tally[key]:>7}{total - tally[key]:>8}")
    checked = sum(tally[k + "_total"] for k, _ in labels)
    agreed = sum(tally[k] for k, _ in labels)
    print(f"\n{agreed}/{checked} agree")
    if misses:
        print("disagreements -- read each one before assuming the cache is wrong:")
        for m in misses[:14]:
            print("   " + m)
        if len(misses) > 14:
            print("   ... and " + str(len(misses) - 14) + " more")
    else:
        print("every field agrees")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
