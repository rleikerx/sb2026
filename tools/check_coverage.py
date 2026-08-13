#!/usr/bin/env python3
"""
Coverage sweep — source material that ships in the export but nothing reads.

This exists because of a defect it would have caught. `decrypt_wpak.py` decrypted only
`*.cfg` and passed every other member of a `.wpak` through untouched, so 703 treasure
tables and six vendor dialogs sat in `export_aegisfall/config/` as ciphertext for months.
Every file was present, every file was the right size, and no check looked at them,
because no check knew they were meant to be looked at.

The generalisation: a file nobody reads and a file nobody *can* read look identical from
outside. So rather than list the things worth checking, this walks what actually ships and
asks, of each, which exporter consumes it — and reports what nothing does.

Two areas so far.

`config`   Every file under `export_aegisfall/config/` against the string literals in
           `tools/*.py`. Literals are treated as globs, so `Ranks_*.cfg` correctly claims
           all 21 rank files. A directory of numbered tables is claimed by its directory
           name. What is left is source material with no reader.

`treasure` The four treasure-table id spaces against each other and against
           `content/items.json`: gentable TABLEID → itemtable, PMODTABLE/SMODTABLE →
           modtypetable, modtypetable TABLEID → modtable, itemtable CACHEID → an item.
           A dangling id is a hole in the data; a table nothing points at is content the
           export can reach but no drop ever will.

Both counts are meant to fall. `loop.ps1` floors them so they cannot quietly rise.

Usage:
    python tools/check_coverage.py
"""

from __future__ import annotations

import fnmatch
import json
import re
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "export_aegisfall" / "config"
CONTENT = REPO_ROOT / "export_aegisfall" / "content"
TOOLS = REPO_ROOT / "tools"

#: Suffixes that are data. TGAs are images the map packs carry and are covered by the
#: icon bundle, not by an exporter reading them as config.
DATA_SUFFIXES = {".cfg", ".txt", ".xml", ".itemtable", ".gentable", ".modtable",
                 ".modtypetable"}

#: Directories whose filenames are bare numbers. A consumer of these globs the directory, so
#: naming the directory claims its contents. Everywhere else a filename means something and
#: has to be claimed by name -- `export_content.py` builds a path through `"Config"`, and
#: letting that claim all 143 files in it would hide the 136 nothing reads.
NUMBERED = {"GeneralItemTables", "ItemTables", "ModTables", "ModTypeTables"}

#: Not a consumer. It writes the bundle, so it necessarily names every directory in it; count
#: it and the sweep reports full coverage of files nothing reads -- which is how the ciphertext
#: went unnoticed in the first place.
PRODUCER = "decrypt_wpak.py"


def literals() -> list[str]:
    """Every string literal in the exporters that names a data file or a table directory."""
    found: set[str] = set()
    for source in sorted(TOOLS.glob("*.py")):
        if source.name in (Path(__file__).name, PRODUCER):
            continue
        text = source.read_text(encoding="utf-8", errors="ignore")
        for quoted in re.findall(r'["\']([^"\'\n]+)["\']', text):
            if Path(quoted).suffix.lower() in DATA_SUFFIXES or quoted in NUMBERED:
                found.add(quoted)
    return sorted(found)


def config_area() -> tuple[int, list[str]]:
    """Files under config/ that no exporter names, directly or by glob."""
    claims = literals()
    claimed_dirs = {c for c in claims if c in NUMBERED}
    unread: list[str] = []
    total = 0
    for path in sorted(CONFIG.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in DATA_SUFFIXES:
            continue
        total += 1
        folder = path.parent.name
        if folder in claimed_dirs:
            continue
        if any(fnmatch.fnmatch(path.name, c) or c.endswith("/" + path.name) or c == path.name
               for c in claims):
            continue
        unread.append(f"{folder}/{path.name}")
    print(f"config    {total} data files ship, {total - len(unread)} read by an exporter, "
          f"{len(unread)} read by none")
    by_dir = Counter(u.split("/")[0] for u in unread)
    for folder, count in by_dir.most_common():
        example = next(u for u in unread if u.startswith(folder + "/"))
        print(f"            {folder:<20} {count:>4}   e.g. {example.split('/', 1)[1]}")
    return len(unread), unread


def split_comment(line: str) -> str:
    """The data half of a row. `#` starts a comment unless it is inside quotes — the item
    tables put the item's name after one, which is where the only human-readable label is."""
    quoted = False
    for index, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        if char == "#" and not quoted:
            return line[:index]
    return line


def rows(folder: str, suffix: str):
    """(table id, tokens) for every live row. Rows commented out wholesale are skipped: they
    are content the designers switched off, and counting them as references would invent
    demand for tables nothing reaches."""
    for path in sorted((CONFIG / folder).glob("*." + suffix)):
        for line in path.read_text(encoding="latin-1", errors="ignore").splitlines():
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            tokens = re.findall(r'"[^"]*"|\S+', split_comment(text))
            if len(tokens) >= 3 and re.fullmatch(r"-?[\d.]+", tokens[0]):
                yield int(path.stem), tokens


def ids(folder: str, suffix: str) -> set[int]:
    return {int(p.stem) for p in (CONFIG / folder).glob("*." + suffix)}


def treasure_area() -> tuple[int, int]:
    """Resolve every id the treasure tables name. Returns (dangling, orphan)."""
    if not (CONFIG / "ItemTables").is_dir():
        print("treasure  not decrypted - run decrypt_wpak.py")
        return 0, 0
    item = ids("ItemTables", "itemtable")
    gen = ids("GeneralItemTables", "gentable")
    mod = ids("ModTables", "modtable")
    modtype = ids("ModTypeTables", "modtypetable")

    dangling: list[str] = []
    used_item: set[int] = set()
    used_modtype: set[int] = set()
    used_mod: set[int] = set()

    for table, tokens in rows("GeneralItemTables", "gentable"):
        target = int(float(tokens[2]))
        used_item.add(target)
        if target not in item and target not in gen:
            dangling.append(f"gentable {table} -> table {target}")
        for column in (5, 7):
            if len(tokens) > column and re.fullmatch(r"-?[\d.]+", tokens[column]):
                which = int(float(tokens[column]))
                if which:
                    used_modtype.add(which)
                    if which not in modtype:
                        dangling.append(f"gentable {table} -> modtype {which}")
    for table, tokens in rows("ModTypeTables", "modtypetable"):
        target = int(float(tokens[2]))
        used_mod.add(target)
        if target not in mod:
            dangling.append(f"modtypetable {table} -> mod {target}")

    cache: set[int] = set()
    for _, tokens in rows("ItemTables", "itemtable"):
        if re.fullmatch(r"\d+", tokens[2]):
            cache.add(int(tokens[2]))

    known: set[int] = set()
    for name in ("items", "deeds", "structures"):
        path = CONTENT / f"{name}.json"
        if path.exists():
            known |= {row["asset_id"] for row in json.loads(path.read_text(encoding="utf-8"))}
    unresolved = cache - known

    orphans = ((item - used_item) | (modtype - used_modtype) | (mod - used_mod))
    print(f"treasure  {len(item) + len(gen) + len(mod) + len(modtype)} tables, "
          f"{len(dangling)} dangling id(s), {len(orphans)} table(s) nothing points at")
    print(f"            CACHEID   {len(cache)} distinct, {len(cache & known)} resolve, "
          f"{len(unresolved)} do not")
    for note in dangling[:5]:
        print(f"            dangling  {note}")
    return len(dangling), len(orphans)


def main() -> int:
    print("coverage sweep - what ships that nothing reads\n")
    unread, _ = config_area()
    print()
    dangling, orphans = treasure_area()
    print(f"\ncoverage|unread={unread}|dangling={dangling}|orphans={orphans}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
