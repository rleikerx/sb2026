#!/usr/bin/env python3
"""
The rules tables: movement speeds, recovery rates, scaling curves, mod types, skills.

Why this exists
---------------
`powers.json` and `effects.json` say what a power costs and what it modifies. They do not
say what any of it *means*, because four small config files carry the meanings and none of
them had been read:

    DefaultSpeeds.cfg    how fast anything moves, walking/running/swimming/flying
    RecoveryRates.cfg    health, mana and stamina regeneration, and stamina burn
    CompoundCurves.cfg   the level-scaling curves every power and effect refers to
    ModTypes.cfg         what each of the 85 mod verbs is and how it behaves
    Skills.cfg           the 94 skills and the attributes that drive each one

**The curve table is the one that changes what the other exports are worth.** Powers and
effects are littered with tokens like `SL0083Up` and `SL1500Up` -- on `HateValue`, on
`MeleeDamageModifier`, on `ACTION` -- and `content/powers.json` could only hand them over
as opaque strings. They are defined here: `SL0083Up` is a `SlopedLine` of slope **0.83** over a
range of 100, and `SL1500Up` is 15.0 -- the four digits are hundredths, which is exactly
the kind of thing worth reading out of the table rather than inferring from the name. With
it the combat numbers become computable rather than quoted:

    Cleave -> effect "Axe" -> MeleeDamageModifier 16.8 SL0083Up
           -> +16.8 damage, +0.83 per level, over a range of 100

That join is checked rather than hoped for: every scale token that appears in Powers.cfg or
Effects.cfg is looked up in the curve table, and any that does not resolve is reported.

Movement in metres
------------------
Speeds are in world units per second. At the units/m `reference/summary.json` measures --
2.5994 as of the joint-frame fix -- that is:

    WALK        6.50 u/s   2.50 m/s    9.0 km/h
    RUN        14.67 u/s   5.64 m/s   20.3 km/h
    COMBATWALK  4.44 u/s   1.71 m/s    6.1 km/h
    COMBATRUN  14.67 u/s   5.64 m/s   20.3 km/h

The metre column is only as good as that scale, and the scale moves when the pose does, so
it is read from `reference/` at run time rather than pinned in this file.

so combat mode costs you your walk but not your run. `DefaultSpeeds.cfg` also keeps the
previous tuning commented out above the live values -- `WALKSPEED 6.88`, `RUNSPEED 15.52`
-- so the direction of travel is visible; those are captured as `superseded`.

These are the defaults. Races override them and `content/races.json` already carries the
per-race numbers: an Aelfborn runs 13.97 against the default 14.67, and an `Animal` 22.93.

Curve grammar
-------------
    <name>  (<range> <curveType> <params...>)*

Segments are read by arity rather than by looking for the next word, because a greedy read
mistakes the second segment's range for the first segment's parameter:
`DefaultCurveUp 5 FlatLine 150 SlopedLine 0.5` is FlatLine over 5 then SlopedLine 0.5 over
150, not FlatLine(150). Arities: `FlatLine` 0, `SlopedLine` 1, `SlopedInitValLine` 1. A row
that does not consume exactly is reported.

Usage:
    python tools/export_rules.py --out export_aegisfall/content
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The metre scale is measured, not fixed: `measure_assets.py` derives it from the Human
# model's height and it moves whenever the pose does. It moved by 5.2% when the joint frame
# landed -- 2.7411 to 2.5994 -- because the pose it had been measured from leaned backwards.
# So it is read from `reference/summary.json` rather than pinned here, and the fallback is
# only for a tree where that has not been generated yet. Which one was used is recorded in
# the output.
FALLBACK_UNITS_PER_METRE = 2.5994


def units_per_metre(export_root: Path):
    """(value, source) from reference/summary.json, or the fallback."""
    summary = export_root / "reference" / "summary.json"
    if summary.exists():
        try:
            data = json.loads(summary.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = None
        found = _find_scale(data)
        if found:
            return found, "reference/summary.json"
    return FALLBACK_UNITS_PER_METRE, "fallback constant"


def _find_scale(node):
    """The units-per-metre figure wherever summary.json happens to nest it."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, (int, float)) and "metre" in key.lower():
                return float(value)
            found = _find_scale(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_scale(value)
            if found:
                return found
    return None


CURVE_ARITY = {"FlatLine": 0, "SlopedLine": 1, "SlopedInitValLine": 1}


def tokens(line: str) -> List[str]:
    return re.findall(r'"[^"]*"|\S+', line.strip())


def unquote(text: str) -> str:
    return text[1:-1] if len(text) > 1 and text[0] == '"' and text[-1] == '"' else text


def number(text: str):
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def read_speeds(path: Path, per_metre: float) -> Dict[str, Any]:
    """Live speeds, and the commented-out ones they replaced."""
    live: Dict[str, float] = {}
    superseded: Dict[str, float] = {}
    for line in path.read_text(encoding="latin-1", errors="ignore").splitlines():
        stripped = line.strip()
        target = superseded if stripped.startswith("#") else live
        found = re.match(r"#?\s*([A-Z]+)=\s*([\d.]+)", stripped)
        if found:
            target[found.group(1)] = float(found.group(2))
    return {
        "unitsPerSecond": live,
        "metresPerSecond": {k: round(v / per_metre, 4) for k, v in live.items()},
        "supersededUnitsPerSecond": superseded,
        "note": ("Defaults. `content/races.json` carries per-race overrides and those win. "
                 "Combat mode lowers the walk and leaves the run alone."),
    }


def read_recovery(path: Path) -> Dict[str, Any]:
    """Regeneration per activity state, and the stamina a run costs."""
    states: Dict[str, Any] = {}
    consumption: Dict[str, Any] = {}
    for line in path.read_text(encoding="latin-1", errors="ignore").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values = [number(v) for v in value.split()]
        if key.strip().startswith("CONSUMPTION"):
            consumption[key.strip()] = values
        elif len(values) == 3:
            states[key.strip()] = {"health": values[0], "mana": values[1],
                                   "stamina": values[2]}
    return {
        "secondsPerPercent": states,
        "consumption": consumption,
        "note": ("Health and mana are seconds to recover 1 percent; stamina is seconds to "
                 "recover 1 point. Zero means no recovery in that state. `CONSUMPTIONRUN` "
                 "is stamina per second while running, out of combat then in combat."),
    }


def read_curves(path: Path, problems: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Curve name -> its segments, read by arity."""
    out: Dict[str, Any] = {}
    for line in path.read_text(encoding="latin-1", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        name, index, segments = fields[0], 1, []
        while index < len(fields):
            if index + 1 >= len(fields):
                problems.append({"curve": name, "issue": "range with no curve type",
                                 "line": stripped})
                break
            span, curve_type = fields[index], fields[index + 1]
            arity = CURVE_ARITY.get(curve_type)
            if arity is None:
                problems.append({"curve": name, "issue": "unknown curve type",
                                 "curveType": curve_type, "line": stripped})
                break
            params = fields[index + 2:index + 2 + arity]
            if len(params) != arity:
                problems.append({"curve": name, "issue": "short parameter list",
                                 "curveType": curve_type, "line": stripped})
                break
            segments.append({"range": number(span), "curve": curve_type,
                             "params": [number(p) for p in params]})
            index += 2 + arity
        if segments:
            out[name] = segments
    return out


def read_mod_types(path: Path) -> Dict[str, Any]:
    """Mod verb -> how it behaves and how the client labels it."""
    out: Dict[str, Any] = {}
    for line in path.read_text(encoding="latin-1", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = tokens(stripped)
        if len(fields) < 2:
            continue
        out[fields[0]] = {
            "behavior": fields[1],
            "displayCategory": fields[2] if len(fields) > 2 else None,
            "displayString": unquote(fields[3]) if len(fields) > 3 else "",
        }
    return out


def read_skills(path: Path) -> Dict[str, Any]:
    """Skill -> the attributes that drive it, weighted, plus its description."""
    out: Dict[str, Any] = {}
    for line in path.read_text(encoding="latin-1", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        head, _, description = stripped.partition("=")
        fields = tokens(head)
        if len(fields) < 3:
            continue
        uid = unquote(fields[0])
        attributes: Dict[str, int] = {}
        rest = fields[3:]
        for i in range(0, len(rest) - 1, 2):
            weight = number(rest[i + 1])
            if isinstance(weight, (int, float)):
                attributes[rest[i]] = weight
        out[uid] = {
            "name": unquote(fields[1]),
            "icon": number(fields[2]),
            "attributes": attributes,
            "description": unquote(description.strip()).replace("\\n", "\n"),
        }
    return out


# Curve names come in three shapes: SL<n>Up/Down (252), SIVL<n> (48) and five Default*.
# The digit after the SL/SIVL prefix is load-bearing -- without it this also matches SLASH
# and SLAY inside effect ids like `SLASH-RES-DB` and `CSR-SLAYPC`, which are not curves and
# were reported as four unresolved tokens until the digit was required.
SCALE_TOKEN = re.compile(r"\b(?:SL|SIVL)\d[A-Za-z0-9]*\b|\bDefault[A-Za-z]+\b")


def scale_tokens(config: Path) -> Dict[str, int]:
    """Every token in Powers/Effects that looks like a curve name, with its use count."""
    counts: Dict[str, int] = {}
    for name in ("Powers.cfg", "Effects.cfg", "PowerActions.cfg"):
        path = config / name
        if not path.exists():
            continue
        for token in SCALE_TOKEN.findall(
                path.read_text(encoding="latin-1", errors="ignore")):
            counts[token] = counts.get(token, 0) + 1
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config",
                    default=str(REPO_ROOT / "export_aegisfall" / "config" / "Config"))
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "content"))
    args = ap.parse_args()
    started = time.time()

    config, out = Path(args.config), Path(args.out)
    if not (config / "CompoundCurves.cfg").exists():
        print("no CompoundCurves.cfg under " + str(config)
              + " -- run tools/decrypt_wpak.py --all first", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)

    problems: List[Dict[str, Any]] = []
    curves = read_curves(config / "CompoundCurves.cfg", problems)
    per_metre, scale_source = units_per_metre(out.parent)
    speeds = read_speeds(config / "DefaultSpeeds.cfg", per_metre)
    recovery = read_recovery(config / "RecoveryRates.cfg")
    mod_types = read_mod_types(config / "ModTypes.cfg")
    skills = read_skills(config / "Skills.cfg")

    # The join that makes powers.json computable: every curve a power or effect names must
    # be in the table. Reported rather than assumed -- an unresolved token is a number the
    # consumer cannot scale, and it should say so out loud.
    used = scale_tokens(config)
    unresolved = {t: n for t, n in sorted(used.items()) if t not in curves}
    if unresolved:
        problems.append({"issue": "scale tokens with no curve definition",
                         "tokens": unresolved})

    payload = {
        "generator": "tools/export_rules.py",
        "note": ("The tables powers.json and effects.json refer to but do not contain. "
                 "`curves` resolves the SL####Up tokens those files carry as strings; "
                 "`modTypes` names the verbs in effects.json's `mods`; `speeds` is in "
                 "world units per second, with metres alongside at "
                 + str(per_metre) + " units/m."),
        "unitsPerMetre": per_metre,
        "unitsPerMetreSource": scale_source,
        "counts": {
            "curves": len(curves),
            "modTypes": len(mod_types),
            "skills": len(skills),
            "curveTokensUsed": len(used),
            "curveTokensUnresolved": len(unresolved),
        },
        "problems": problems,
        "speeds": speeds,
        "recovery": recovery,
        "curves": curves,
        "modTypes": mod_types,
        "skills": skills,
    }
    (out / "rules.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")

    print("curves " + str(len(curves)) + "  modTypes " + str(len(mod_types))
          + "  skills " + str(len(skills)))
    metres = speeds["metresPerSecond"]
    print("  run " + str(speeds["unitsPerSecond"].get("RUNSPEED")) + " u/s = "
          + "%.2f m/s" % metres.get("RUNSPEED", 0)
          + ", combat walk %.2f m/s" % metres.get("COMBATWALKSPEED", 0))
    print("  curve tokens used by powers/effects: " + str(len(used))
          + ", unresolved " + str(len(unresolved)))
    if problems:
        print("  " + str(len(problems)) + " problems: "
              + "; ".join(p["issue"] for p in problems[:3]))
    print("wrote " + str(out / "rules.json") + "  in %.1fs" % (time.time() - started))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
