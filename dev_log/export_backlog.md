# Export backlog — completeness sweeps

The `content/` tables and the 147 config archives have been swept field-by-field against
what the exporters actually read. **The asset bundles have not**, and this file tracks that.

The method that worked for `content/`: for each bundle, ask what it *references* and
whether every reference resolves. A bundle that is internally consistent can still be
missing everything a consumer needs, and an always-empty column looks exactly like a
correct one. Nine defects this pass were of that shape.

**The config sweep had a hole of exactly that shape, and it was the sweep's own premise.**
"147 config archives" counted the `.cfg` files. `decrypt_wpak.py` decrypted only `*.cfg`
and wrote every other member of a `.wpak` back out untouched, so 727 more files — the 703
treasure tables, the six vendor dialogs, 17 `.txt` and one `.xml` — shipped as ciphertext.
They were present, they were the right size, and nothing read them, which from outside is
indistinguishable from nothing *needing* to read them. They decrypt with the key that was
already in the file; no new cryptanalysis was involved. Two consequences worth keeping:

- A count is the weak half of a check. Every one of those files would have passed a
  file-count assertion on every run.
- `tools/check_coverage.py` now walks what ships and asks which exporter reads it, and
  `loop.ps1` runs it with ceilings. That is the general form of this defect, so the next
  one of these should announce itself.

**This backlog is finite.** When the unchecked list is empty the sweep is over; the
remaining questions need a running client or server and cannot be answered by reading. Do
not invent items to keep it alive — a manufactured export is worse than no export, and
every defect fixed today came from a plausible-looking claim nobody had tested.

## Swept

| what | result |
|---|---|
| COBJECT records, all 7 asset kinds | 9 defects; `content/` grew from 6 tables to 15 |
| 147 config archives | 4 mechanical configs found and exported; the rest is UI |
| `icons/atlas.json` vs every `icon_texture_id` in `content/` | **1,576 / 1,576 resolve.** Note the atlas is keyed by `texture_id`, not `asset_id` — matching on `asset_id` gives a spurious 238/1,576 |
| every `.wpak` member vs the decrypted bundle | **930 / 930 plaintext**, up from 203. `decrypt_wpak.py --verify` asserts it per run |
| the four treasure-table id spaces against each other | 703 tables, **one dangling id** (`3100.gentable` wants table 3103, which does not ship), 107 tables nothing points at |
| every `CACHEID` in `ItemTables/` vs `content/` | 1,593 distinct; **1,490 resolve** against items + deeds + structures. The 103 that do not are runes, in two id spaces `content/` does not carry: 47 at 3001–3119 (45 of their names are in `disciplines.json`) and 56 at 250000–252127, the stat runes — *Enhanced Strength*, *Amazing Spirit*, *Constitution of the Gods* |

## Not yet swept

- [ ] `models/` + `textures_2x/` — does every texture a model references exist?
- [ ] `models_rigged/` + `rig/` — does every rigged model bind to a skeleton that ships?
- [ ] `motions/` + `animations/` — does every ANIMID referenced by `powers.json`,
      `effects.json` and `overrides.json` resolve per skeleton?
- [ ] `sounds/` — do the `obj_sound_events` / `static_sound` ids on COBJECT records resolve?
- [ ] `effects/` bundle vs `content/effects.json` — are they the same population?
- [ ] `cameos/` vs `powers.json` — how many powers have no cameo, and is that real?
- [ ] `maps/terrain/` vs `zones/` — 178 heightmaps against 861 zones; which zones have none?
- [ ] `graph/` — what is in it and what references it?
- [ ] **The treasure tables — 703 files, decrypted and unexported.** The largest unexported
      body of mechanical data left. Four id spaces that chain: a `.gentable` is a region's
      drop table and names an `ITEMTYPE`, a `TABLEID` into `ItemTables/` and a prefix and
      suffix `MODTABLE` into `ModTypeTables/`, which in turn name a `ModTables/` row holding
      the actual modifier — `Steel 0 2`, `ChaosOre 0 20`. Rows are `MIN% MAX%` bands.
      Schema is settled (see `check_coverage.py`, which parses all four); what is missing is
      an exporter and a decision on shape. Two things to keep when writing it: **387 rows
      are commented out**, which is content the designers switched off and not noise, and
      the item's only human-readable name lives *after* the `#` on its row.
- [ ] **What points at a `.gentable`?** The chain resolves downward from a region table but
      nothing found so far names the region tables themselves. Until that is answered the
      loot data is a closed system with no entry point. Likely a mob or zone field —
      `ArcCityAssetTemplate.template_loot_trigger` is the only loot-shaped field in
      `arcane/`, and it is a string, not one of these ids.
- [ ] `Guild_Restrictions.*` — **56 files, not 57**, and not near-identical where it matters.
      52 are the permissive all-`Any` default; **4 carry the real charter membership rules**
      (`Decay`+`Tyranny` identical, `Saedron`+`Vindication` identical, the two pairs differing
      only in class lists). Amazon is `SEX= "Female"`; Aracoix, Centaur, Dwarves and Virakt
      are single-race. **Corroboration worth having: the only three guild types left open in
      both restrictive rulesets are Coven, Pirates and Heralds** — the same three the README
      shows have no charter deed and no wiki page. A fourth independent source calling them
      stubs. Export blocked on nothing but a decision; two parser traps are recorded in the
      README section. Fix the 57 in `README.md:1607` and `:1623` at the same time.
- [ ] `RaceClassDiscTalents.cfg` — UID → English name table; useful for resolving tokens
- [ ] The rune id spaces the item tables name and `content/` does not carry: 3001–3119
      (disciplines) and 250000–252127 (stat runes). Are they COBJECT records this export
      skips, or do they exist only as loot-table entries?
- [ ] Text bundles — decide in or out of "mechanical data only", and record the decision
      either way. **The six vendor dialogs now decrypt and belong in this decision**:
      `VendorDialog`, `TrainerDialog`, `DiscTrainerDialog`, `RunemasterDialog`,
      `ZoneLoreDialog`, `OtherDialog`, UTF-16, from the client's `Lore/` directory. Plus the
      original four: `Emotes.cfg`, `ToolTips.cfg`, `PassiveMessageText.cfg`, `XNames.cfg`.
- [ ] `lore/biomes.json` — **agreed, not yet written.** `<ZONELORE>` across the three
      `ZoneDataENGLISH.cfg` is 147 zone entries but only **36 distinct blurbs**, 32.7 KB:
      the lore is biome-level and reused verbatim, so key it by blurb with the zone list
      rather than duplicating it four deep. `export_zones.py:248` currently skips it.

## Needs a running client or server — not reachable by reading

- `unknown15`, and which of `animIdA`/`animIdB` starts a cast
- the wiki's +1 s casting-time offset on 225 spells
- the Tree of Life health ladder, and whether `TREEOBJECTID= 547` means anything
- `Blood of the Dragon`'s missing movement bonus
- five powers disagreeing on `Requires Hit Roll`
