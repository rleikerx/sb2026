#!/usr/bin/env python3
"""
Powers and effects as JSON, out of the decrypted config archives.

Why this exists
---------------
`content/` reads the COBJECT cache, so it has races, classes, items and structures. The
1,465 powers and 2,950 effects are not in that cache -- they are in the Blowfish-encrypted
`.cfg` archives, which is why they were still raw text long after everything else had a
table. `tools/decrypt_wpak.py --all` opened them; this reads them.

Powers are worth reading straight rather than scraping: the wiki lists about 460 of them,
this is all 1,465, with the cost, the prerequisites and the message strings the client
actually shipped.

The two files are one chain and are emitted together, because neither answers much alone:

    Powers.cfg        what a power costs, targets and requires, and its ACTION list
    PowerActions.cfg  what an ACTION does, and which effects it applies
    Effects.cfg       what an effect modifies for as long as it lasts

so `powers.json` carries each power's actions already resolved to effect ids, and
`effects.json` carries each effect's `appliedBy` back-reference.

On field names
--------------
`Effects.cfg` documents its own header (`#EffectID EffectName Icon`). `Powers.cfg` does
not: its 22 positional header fields are unnamed, and the client parses them positionally
into unnamed struct slots (`sb.exe` 0x56e410 -- 22 fields, each with its own error branch,
which is what pins the count). So the names here are evidenced, not decreed:

    areaRadius   non-zero on exactly the powers whose areaShape is not NONE
    costType     4 values, MANA/STAMINA/NONE/HEALTH, against a numeric costAmount
    usableIn     3 values, BOTH/COMBAT/NONCOMBAT
    targeting    4 values, NONE/CLICK/NEARBYMOBS/NAME
    animIdA/B    both header slots resolve against `animations/resolve.json`, and they are
                 set together with LOOPANIMID on 674 powers -- 529 of the 560 whose cast
                 time is 2 s or more, against 47 of the 709 instant ones. Three animation
                 phases of a cast, then. Which of the two is the start and which the finish
                 is NOT established, so they are handed over as a pair rather than named.

Five fields have no reading worth stating and are passed through as `unknown<n>` with
their raw value. Naming them on a hunch would be worse than leaving them legible.

Damaged records are reported, not repaired
------------------------------------------
The shipped config has three authoring bugs, and all three survive into `problems`:

    POWEREND= COSTAMT SL0050Up   a key written onto the block terminator (line 19434)
    SRDX-DB                      25 header fields: SPELL/skill/name appears twice
    PRL-033                      castSeconds reads "2.9.0"

Usage:
    python tools/export_powers.py --out export_aegisfall/content
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Shared with the animation export on purpose: two readers of one grammar would drift, and
# `overrides.json` and `effects.json` disagreeing about what an effect contains would be a
# bad way to find that out.
from export_animation_table import block_head, cfg_blocks

HEADER_FIELDS = [
    "code", "name", "kind", "skillId", "skillName", "target", "range", "areaShape",
    "areaRadius", "areaAffects", "costType", "costAmount", "unknown12", "unknown13",
    "castSeconds", "unknown15", "unknown16", "unknown17", "usableIn",
    "animIdA", "animIdB", "targeting",
]
NUMERIC = {"skillId", "range", "areaRadius", "costAmount", "castSeconds",
           "unknown12", "unknown13", "unknown15", "unknown16", "unknown17",
           "animIdA", "animIdB"}
# Keys whose value is a single quoted sentence shown to the player.
MESSAGE_KEYS = {
    "DESCRIPTION", "INITSTRING", "SUCCESSSELF", "SUCCESSOTHER", "FIZZLESELF",
    "FIZZLEOTHER", "APPLYEFFECTSELF", "APPLYEFFECTOTHER", "APPLYEFFECTCASTER",
    "APPLYEFFECTTARGET", "WEAROFFEFFECTSELF", "WEAROFFEFFECTOTHER",
    "APPLYDAMAGESELF", "APPLYDAMAGEOTHER", "APPLYDAMAGECASTER", "APPLYDAMAGETARGET",
}
BOOL_KEYS = {"CANCASTWHILEMOVING", "CANCASTWHILEFLYING", "SHOULDCHECKPATH", "STICKY",
             "ISADMINPOWER", "BLADETRAILS"}


def tokens(line: str) -> List[str]:
    """Whitespace split that keeps a quoted string whole."""
    return re.findall(r'"[^"]*"|\S+', line.strip())


def unquote(text: str) -> str:
    return text[1:-1] if len(text) > 1 and text[0] == '"' and text[-1] == '"' else text


def number(text: str):
    """int, float, or the raw string when the source wrote something that is neither."""
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def camel(key: str) -> str:
    """CANCASTWHILEMOVING -> cancastwhilemoving. Lowercased, not word-split.

    These keys are single uppercase runs with no separators, so there is nothing to split
    on without a word list. Inventing one would put `applyEffectSelf` next to a key it
    guessed wrong, and the caller cannot tell which is which.
    """
    return key.lower()


def read_powers(path: Path, problems: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Every POWERBEGIN block: its header, its keys, and its ACTION list."""
    out: Dict[str, Any] = {}
    for lines in cfg_blocks(path, "POWERBEGIN", "POWEREND"):
        head = next((l for l in lines if l.strip()), None)
        if head is None:
            continue
        fields = tokens(head)
        code = unquote(fields[0])
        row: Dict[str, Any] = {}
        if len(fields) != len(HEADER_FIELDS):
            # Do not name the fields of a header that is the wrong length. SRDX-DB repeats
            # its kind/skillId/skillName triple, so every field after it is shifted, and
            # labelling them anyway would hand the caller `areaRadius: "PCMOBILE"` with
            # nothing to say it is wrong. The tokens are kept verbatim instead.
            problems.append({"power": code, "issue": "header field count",
                             "expected": len(HEADER_FIELDS), "got": len(fields),
                             "line": head.strip()})
            row["code"] = code
            row["name"] = unquote(fields[1]) if len(fields) > 1 else ""
            row["headerUnparsed"] = [unquote(f) for f in fields]
        else:
            for name, value in zip(HEADER_FIELDS, fields):
                value = unquote(value)
                if name in NUMERIC:
                    parsed = number(value)
                    if isinstance(parsed, str):
                        problems.append({"power": code,
                                         "issue": name + " is not a number",
                                         "value": value})
                    row[name] = parsed
                else:
                    row[name] = value

        actions: List[Dict[str, Any]] = []
        messages: Dict[str, str] = {}
        flags: Dict[str, bool] = {}
        extra: Dict[str, Any] = {}
        for line in lines:
            found = re.match(r"\s*([A-Za-z][\w]*)=\s*(.*)$", line)
            if not found:
                continue
            key, value = found.group(1), found.group(2).strip()
            if key == "ACTION":
                parts = tokens(value)
                actions.append({"id": parts[0],
                                "args": [number(unquote(p)) for p in parts[1:]]})
            elif key in MESSAGE_KEYS:
                # Repeats, and the last one does not win: 162 powers write DESCRIPTION
                # twice and 2 write WEAROFFEFFECT twice. Assigning would have thrown away
                # 190 descriptions without saying so.
                name = camel(key)
                text = unquote(value)
                if name in messages:
                    if not isinstance(messages[name], list):
                        messages[name] = [messages[name]]
                    messages[name].append(text)
                else:
                    messages[name] = text
            elif key in BOOL_KEYS:
                flags[camel(key)] = value.upper() == "TRUE"
            else:
                parsed_list = [number(unquote(p)) for p in tokens(value)]
                parsed = parsed_list[0] if len(parsed_list) == 1 else parsed_list
                name = camel(key)
                if name in extra:
                    # Repeated keys keep every occurrence: EQPREREQ and EFFECTPREREQ are
                    # lists, and taking the last would silently drop a requirement.
                    if not isinstance(extra[name], list) or not extra[name] or \
                            not isinstance(extra[name][0], list):
                        extra[name] = [extra[name]]
                    extra[name].append(parsed)
                else:
                    extra[name] = parsed
        row["actions"] = actions
        if messages:
            row["messages"] = messages
        if flags:
            row["flags"] = flags
        row.update(extra)
        out[code] = row
    return out


def read_effects(path: Path, problems: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Every EFFECTBEGIN block: header, sources, mods, conditions, anim overrides."""
    out: Dict[str, Any] = {}
    for lines in cfg_blocks(path, "EFFECTBEGIN", "EFFECTEND"):
        effect_id, name = block_head(lines)
        if effect_id is None:
            continue
        head = next((l for l in lines if l.strip() and not l.strip().startswith("#")), "")
        fields = tokens(head)
        if len(fields) != 3:
            problems.append({"effect": effect_id, "issue": "header field count",
                             "expected": 3, "got": len(fields), "line": head.strip()})

        sources: List[str] = []
        mods: List[Dict[str, Any]] = []
        conditions: List[Dict[str, Any]] = []
        overrides: List[List[int]] = []
        flags: List[str] = []
        section = None
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.endswith("BEGIN"):
                section = stripped[:-5]
                continue
            if stripped.endswith("END"):
                section = None
                continue
            parts = tokens(stripped)
            if section is None:
                # Effect-level flags sit outside every sub-block: IsItemEffect (717),
                # ISSPIREEFFECT (23), DontSave (5), IGNORENOMOD (3). Skipping whatever was
                # not in a section dropped all 748, and IsItemEffect is the one that says
                # an effect comes from an item rather than a power -- which is most of the
                # answer to why an effect has no `appliedBy`.
                if stripped != head.strip():
                    flags.append(stripped)
                continue
            if section == "SOURCE":
                sources.append(stripped)
            elif section == "MODS":
                if parts[0] == "AnimOverride":
                    # [source, *targets]: 156 lines name two replacements for one slot.
                    ids = [int(p) for p in parts[1:] if p.isdigit()]
                    if len(ids) >= 2:
                        overrides.append(ids)
                mods.append({"name": parts[0],
                             "args": [number(unquote(p)) for p in parts[1:]]})
            elif section == "CONDITION":
                conditions.append({"name": parts[0],
                                   "args": [number(unquote(p)) for p in parts[1:]]})

        out[effect_id] = {
            "name": name,
            "icon": number(fields[2]) if len(fields) > 2 else None,
            "sources": sources,
            "mods": mods,
            "conditions": conditions,
        }
        if flags:
            out[effect_id]["flags"] = flags
        if overrides:
            out[effect_id]["animOverrides"] = overrides
    return out


def read_actions(path: Path, effect_ids: set) -> Dict[str, Any]:
    """Power action id -> verb, the effects it names, and its own keys."""
    out: Dict[str, Any] = {}
    for lines in cfg_blocks(path, "POWERACTIONBEGIN", "POWERACTIONEND"):
        action_id, _ = block_head(lines)
        if action_id is None:
            continue
        head = next((l for l in lines if l.strip() and not l.strip().startswith("#")), "")
        fields = head.split()
        keys: Dict[str, Any] = {}
        for line in lines:
            found = re.match(r"\s*([A-Za-z][\w]*)=\s*(.*)$", line)
            if not found:
                continue
            value = found.group(2).strip()
            if value.upper() in ("TRUE", "FALSE"):
                keys[camel(found.group(1))] = value.upper() == "TRUE"
            else:
                keys[camel(found.group(1))] = [number(unquote(p)) for p in tokens(value)]
        row = {
            "verb": fields[1] if len(fields) > 1 else "",
            "args": [number(f) for f in fields[2:]],
            # Membership, not position: the verbs disagree about where the effect sits.
            # `ApplyEffect` puts it first, `ApplyEffects` puts two after a count, and
            # `DeferredPower` names one to apply now and one to defer.
            "effects": [f for f in fields[2:] if f in effect_ids],
        }
        if keys:
            row["keys"] = keys
        out[action_id] = row
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config",
                    default=str(REPO_ROOT / "export_aegisfall" / "config" / "Config"))
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "content"))
    args = ap.parse_args()
    started = time.time()

    config, out = Path(args.config), Path(args.out)
    if not (config / "Powers.cfg").exists():
        print("no Powers.cfg under " + str(config)
              + " -- run tools/decrypt_wpak.py --all first", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)

    problems: List[Dict[str, Any]] = []
    effects = read_effects(config / "Effects.cfg", problems)
    actions = read_actions(config / "PowerActions.cfg", set(effects))
    powers = read_powers(config / "Powers.cfg", problems)

    # A key written onto a block terminator ends the block early and takes its value with
    # it. `cfg_blocks` cannot see that -- the line does start with POWEREND -- so it is
    # looked for here rather than left to be noticed by whoever misses the field.
    for number_, line in enumerate(
            (config / "Powers.cfg").read_text(encoding="latin-1",
                                              errors="ignore").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("POWEREND") and stripped != "POWEREND":
            problems.append({"issue": "key written onto the block terminator",
                             "line": stripped, "lineNumber": number_,
                             "consequence": "the value on this line is not in any power"})

    # Resolve each power's actions to effects, and give every effect the reverse link.
    applied_by: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for code, power in powers.items():
        named: List[str] = []
        for action in power["actions"]:
            entry = actions.get(action["id"])
            if entry is None:
                problems.append({"power": code, "issue": "ACTION names no power action",
                                 "action": action["id"]})
                continue
            action["verb"] = entry["verb"]
            action["effects"] = entry["effects"]
            for effect_id in entry["effects"]:
                if effect_id not in named:
                    named.append(effect_id)
                applied_by[effect_id].append({"power": code, "name": power["name"]})
        power["effects"] = named
    for effect_id, users in applied_by.items():
        seen = {u["power"]: u for u in users}
        effects[effect_id]["appliedBy"] = sorted(seen.values(), key=lambda u: u["power"])

    # `appliedBy` alone reads as though 1,656 effects were dead, and they are not: 2,908 of
    # the 2,950 are named by *some* power action, but only 1,294 by an action a power lists
    # in its own ACTION=. The rest are reached indirectly -- `DeferredPower` names a second
    # effect to fire later, and items carry procs -- so the action link is recorded too and
    # the difference between the two counts is the chained set.
    named_by_action: Dict[str, List[str]] = defaultdict(list)
    for action_id, entry in actions.items():
        for effect_id in entry["effects"]:
            named_by_action[effect_id].append(action_id)
    for effect_id, action_ids in named_by_action.items():
        effects[effect_id]["namedByActions"] = sorted(set(action_ids))

    orphans = [e for e in effects if "namedByActions" not in effects[e]]
    no_power = [e for e in effects if "appliedBy" not in effects[e]]
    with_over = sum(1 for e in effects.values() if e.get("animOverrides"))

    (out / "powers.json").write_text(json.dumps({
        "generator": "tools/export_powers.py",
        "note": ("Powers.cfg, all 1,465. `actions` are resolved to the effects they apply "
                 "and `effects` is that list flattened. `animIdA`/`animIdB` and "
                 "`loopanimid` are ANIMIDs -- resolve them through animations/resolve.json "
                 "per skeleton. `unknown12/13/15/16/17` are unnamed header slots, passed "
                 "through rather than guessed at. Keys other than the header keep the "
                 "source's own spelling, lowercased."),
        "count": len(powers),
        "problems": problems,
        "powers": powers,
    }, indent=1), encoding="utf-8")

    (out / "effects.json").write_text(json.dumps({
        "generator": "tools/export_powers.py",
        "note": ("Effects.cfg, all 2,950. `mods` is what the effect changes while it is up "
                 "and `conditions` is what ends it, both as {name, args} because the "
                 "argument lists are per-verb. `animOverrides` rows are [source, *targets] "
                 "-- see animations/overrides.json for the same data joined to powers. "
                 "`namedByActions` is every power action that names the effect; "
                 "`appliedBy` is the narrower set of powers that list such an action in "
                 "their own ACTION=. An effect with the first and not the second is "
                 "reached indirectly, e.g. as the deferred half of a DeferredPower."),
        "count": len(effects),
        "effects": effects,
    }, indent=1), encoding="utf-8")

    print("powers " + str(len(powers)) + "  effects " + str(len(effects))
          + "  power actions " + str(len(actions)))
    print("  effects: " + str(len(effects) - len(no_power)) + " reachable from a power, "
          + str(len(effects) - len(orphans)) + " named by some power action, "
          + str(len(orphans)) + " by neither; " + str(with_over) + " carry an AnimOverride")
    print("  " + str(len(problems)) + " damaged records reported: "
          + "; ".join(str(p.get("power") or p.get("effect")) + ": " + p["issue"]
                      for p in problems[:4]))
    print("wrote " + str(out) + "  in %.1fs" % (time.time() - started))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
