# Shadowbane cache export — available to Aegisfall

**Location:** `C:\Code\sb2026\export_aegisfall\`
**Status:** built, verified, sitting on disk. Nothing has been copied into
`C:\Code\adventure` — that call is yours.

Everything here was decoded from the original Shadowbane client caches
(`C:\Code\Shadowbane - Throne of Oblivion\cache\`) by the tools in
`C:\Code\sb2026\tools\`. All CPU, all deterministic, all re-runnable.

**These are reference material, not shipping assets.** Aegisfall is authoring its
own art; this exists to consult while doing that. That framing is why the scale
table and the content tables below are probably worth more to you than the
1.8 GB of geometry.

## Start here if you are restarting an integration

Everything below is the full reference. This is what changed on the 11 Aug pass and what it
means for a pass that begins again from scratch. Detail for each item is in its own section;
the reasoning is in `dev_log/081126.md`.

### One defect explains most of it

`ArcSkeleton.pose()` never applied the ASF joint frame, so **every animated clip leaned about
13° backwards** and the Aracoix held its wings out horizontally instead of folded. It is
fixed. That single fix moved five things that had been calibrated against the broken pose, so
some numbers you may already have baked are wrong rather than merely stale.

### Re-take these — they changed

| bundle | what changed |
|---|---|
| `motions/tracks/` | rotations are now **parent-frame**; apply by name with no rig lookup |
| `animations/` | repackaged; gains `overrides.json` |
| `models/` (creature) | re-baked on the fixed pose |
| `graph/` | re-baked on the fixed pose |
| `reference/` | **`unitsPerMetre` 2.7411 → 2.5994** — see below |
| `content/items.json` | `damage` was empty on all 4,021 rows; race/class restrictions were **inverted** on 675 |
| `content/disciplines.json`, `talents.json` | race/class requirements were **inverted**; six new columns — see below |
| `content/powers.json` | gains an `actions` table, without which 19 rune effects are unreachable |

### Take these — they are new

| bundle | what it is |
|---|---|
| `content/powers.json` | all 1,465 powers, against the ~460 the wiki lists |
| `content/effects.json` | 2,950 effects — what a power actually does |
| `content/rules.json` | speeds, recovery, the 305 scaling curves, 84 mod types, 94 skills |
| `maps/terrain/` | all 178 zone heightmaps **plus the transform that places them** |
| `animations/overrides.json` | what an active effect plays instead of what |

### Leave these — they did not move

`models/` non-creature (the 1.2 GB of structures, props, items, deeds), `models_rigged/`,
`rig/`, `zones/`, `content/` races/classes/structures, `icons/`, `sounds/`, `terrain/`,
`effects/`, `config/`, `cameos/`, `maps/` (the three world images).

**Only creatures carry a skeleton** — zero structures, props, items or deeds do, checked
against the cache itself — so no building or prop is affected by a pose fix, ever.

### The one number to fix before anything else

**`unitsPerMetre` is 2.5994.** It was 2.903, then 2.7411. Anything baked at 2.903 is ~11% off
and anything at 2.7411 is ~5.2% off, including `unitsPerMetre` in Aegisfall's `structures/`,
`weapons/` and `world/` manifests.

It moved because it is derived from a *posed* model's height, and the pose it was measured
from stood on its toes: the cache's rest pose points the foot straight down, so the bounding
box was 0.310 units taller than a person standing flat-footed. It will move again if the pose
does — which is why `content/rules.json` and `maps/terrain/terrain.json` read it out of
`reference/summary.json` at run time and record `unitsPerMetreSource`. **Read it, do not
copy it.**

### Regenerating from nothing

Order matters in two places only — `rig/` before the motion tracks, and `reference/` before
anything that reports metres:

```bash
python tools/export_skeletons.py                        # rig/
python tools/export_assets.py --all                     # models/
python tools/export_assets.py --kind Creature --hierarchy --rest-pose                               --out export_aegisfall/models_rigged
python tools/export_motion_tracks.py                    # motions/tracks
python tools/export_animation_table.py                  # ANIMID tables + overrides
python tools/package_animations.py                      # animations/index.json
python tools/measure_assets.py                          # reference/  <- sets the scale
python tools/export_content.py                          # content/ races, classes, items
python tools/export_powers.py                           # content/ powers, effects
python tools/export_rules.py                            # content/ rules   <- reads the scale
python tools/export_terrain.py                          # maps/terrain     <- reads the scale
python tools/export_zones.py ; python tools/export_graph.py --all
```

Everything else in the `Regenerating` section at the bottom is unchanged and order-free.

---

## Look before you take

```bash
cd C:\Code\sb2026
python tools/serve_export.py        # then open http://localhost:8777/viewer/
```

A searchable browser for all 9,924 models — filter by category or name/ID, click
to load, orbit/zoom, with part count, texture count, dimensions and skeleton
shown per asset. Uses vendored three.js; no network, nothing to install.

## What you can have

| Bundle | Size | State | What it gives you |
|---|---:|---|---|
| `content/` | 7.2 MB | **ready** | shipped-game tuning numbers — races, classes, items, structures, **1,465 powers, 2,950 effects and the rules tables** |
| `zones/` | 9.4 MB | **ready** | **the world** — 861 zones, 47,315 placements, 6,396 spawns |
| `maps/` | 12.1 MB | **ready** | the three continent maps, their territory keys, 48 markers, **and all 178 zone heightmaps** |
| `reference/` | 4.6 MB | **ready** | world-space dimensions + a derived metre scale |
| `sounds/` | 161 MB | **ready** | 1,086 WAVs, 49.2 min |
| `icons/` | 50 MB | **ready** | 6,081 icons as 7 atlas pages + rects |
| `icons_png/` | 51 MB | **ready** | the same art as 8,377 individual named PNGs |
| `terrain/` | 132 MB | **ready** | 20,912 ground blend masks |
| `effects/` | 7.8 MB | **ready** | particle/FX and terrain tile definitions, **+ their 132 textures** |
| `cameos/` | 3.1 MB | **ready** | the 195 power icons — **not from the cache**, see below |
| `graph/` | 37 MB | **ready** | **the assembly graph** — 90,596 parts: mesh, texture, joint, transform |
| `rig/` | 2.4 MB | **ready** | **103 skeletons**, 4,228 bones with bind pose, joint axis and mirror flags |
| `motions/` | 70 MB | **ready** | **all 1,503 motion clips** as per-bone quaternion tracks, at the source's frame rate |
| `models_rigged/` | 612 MB | **ready** | the 2,380 creatures as *rigs* — one node per bone, at rest, for the tracks to drive |
| `animations/` | 4 MB | **ready** | the manifest that joins the three above: model -> rig -> action -> clip |
| `config/` | 7.0 MB | **ready** | **200 decrypted .cfg files** — 1,465 powers, effects, zone tables |
| `models/` (non-creature) | 1.2 GB | **ready** | 7,544 GLB — structures, props, items, deeds |
| `models/` (creature) | 590 MB | **needs work** | 2,380 GLB, posed standing — see the rig caveat below, and regenerate: these carry the old backward lean |
| `textures_2x/` | 1.5 GB | **skip** | Lanczos upscales of art you're replacing |
| `viewer/` | 4 MB | tooling | the browser above, vendored; served by `tools/serve_export.py` |

Smallest useful slice: `content/` + `reference/` is **11.8 MB** and is arguably
the highest-value part of the whole export. `content/` grew: it now carries the
1,465 powers and 2,950 effects as well.

---

## zones/ — where everything stands

`models/` answers *what a building looks like*. This answers *where it stands*,
and it is the bundle that turns the other 1.2 GB from a parts bin into a world.

```
zones/index.json                        861 zones: name, type, radii, counts
zones/placements/10160_City_of_Dalgoth.json
zones/required_models.json              the models the world actually places
```

| | |
|---|---:|
| zones | 861 |
| prop placements | 47,315 |
| mobile spawns | 6,396 |
| distinct models placed | 1,428 |
| placements that resolve to a model in `models/` | **47,315 of 47,315** |

Every placement carries `assetId`, resolved `name` and `kind`, a world `pos`,
and `yRot`. Props nest, so a cathedral's pews and altar arrive inside it with a
`depth` — the export recurses and keeps the relationship. Buildings keep the
zone's own label where it overrode the model name (`Cathedral of the All Father`
standing in Dalgoth as *Basilica of the Patriarchs*).

Spawns are identified by **rune stones, not by template ID** — every mobile in
the cache carries template `0`, so the runes are the identity, and they resolve:
`Father Keldran, Master Prelate` comes back as `Human Guard` + `Master Prelate`
+ `Shopkeeper` with level 40 and a 120 s respawn. 5,140 of 6,396 spawns carry a
non-zero position; the remaining 1,256 sit at their building's origin, which is
what the source says rather than a decode failure.

### required_models.json is the point

Without it, *"which of the 1,057 structures do we need?"* is a judgement call.
With it, it is a lookup — every distinct asset the world places, most-placed
first, with its count:

| kind | distinct models placed |
|---|---:|
| Prop | 1,115 |
| Structure | 310 |
| Item / other | 3 |

**80% of all 47,315 placements come from the top 445 models**, so a client that
stages those 445 draws four fifths of the world; the tail is long and cheap to
defer.

### The world is slot-based, and that is a finding rather than a limitation

**Zones are portable content packs and the continents are empty terrain waiting
for them.** Four independent things in the cache say so, and they agree:

1. **858 of 861 zones declare their coordinates `LOCAL`** (`zone_tile_cord_type`;
   only three are `GLOBAL`). A zone states outright that its positions are
   relative to something else.
2. **The continents hold zero props of their own** — 27 large zones are empty,
   and three of them are named `North Container 1`, `2` and `3`. The source
   called them containers.
3. **178 zones carry their own terrain heightmap** (`terrain_type 7`,
   `terrain_image`), so a zone brings its own ground rather than inheriting it.
4. **`CZone.cache` has no parent field at all.** Nothing was stripped; the link
   was never in the client, because the server assigns it.

So a zone is not a *place* in this data — it is a *thing that can be placed*,
and the same village could sit on a different continent next build. That is why
there is no map file to find: the map is an assignment, and it lives server-side.

| continent | major radius | ≈ km at 2.741 units/m | heightmap |
|---|---:|---:|---|
| Seafloor | 65,536 | 22.6 | — (flat, type 4) |
| The Dalgoth Marches | 49,152 | 16.9 | `1005813` |
| Khar Thale Islands | 32,768 | 11.3 | `1005400` |
| Tyrranth Major | 32,768 | 11.3 | `1005810` |
| Vorringia | 28,672 | 9.9 | `1005821` |
| Valkyria | 24,576 | 8.5 | `1005210` |

**All 14 continent heightmaps resolve in `Textures.cache`**, and so do another 164 —
**178 in total, now extracted** to `maps/terrain/` with the transform that places them. See
that section below. Those images are the continent shapes, which is the closest thing to
"the three maps" the client actually ships.

What you can do today: draw any single zone faithfully — `City of Dalgoth` and
its 1,873 placements is a complete, self-consistent scene. What you cannot do
from this bundle alone: assemble them into one continuous world.

`zoneType`, incidentally, is the zone's *shape* — `0` elliptical, `1`
rectangular — not a level in a hierarchy, and it should not be read as one.

---

## maps/ — the three worlds as pictures

**These are not in any cache.** They sit in the install's `Maps/` folder, which is why nothing here
had read them: every other tool in this repo opens a `*.cache`. Plain uncompressed TGA, plus a
`.wpak` that is an ordinary ZIP. `python tools/export_maps.py`.

| world | map | territories | highlight |
|---|---|---|---|
| Aerynth | 1024×512 | 1024×512 | 512×256 |
| Dalgoth | 1024×512 | 1024×512 | 512×256 |
| Vorringia | 1024×512 | 512×512 | 256×256 |

Plus one shared set of **48 marker icons** (`B_*` terrain badges, `T_*` faction markers), written
once and referenced by all three worlds.

**The labelled landmasses are the macrozones `CZone.cache` already gives radii for**, which is what
makes these worth having rather than merely nice to look at:

- *Aerynth* — Tyrranth Major, Tyrranth Minor, Khar Thale Islands, Stormvald, Maelstrom, Oblivion,
  The Forbidden Isle
- *Dalgoth* — The Northern Reaches, Relloth, Anderon, The Parched Isles, Haven Isle, Maelstrom,
  Oblivion
- *Vorringia* — Vorringheim, Uthgaard, Jov Hir'akar, The Sinking Isles, Vander's Doom, Terminus,
  Oblivion, Maelstrom

So `Tyrranth Major` is a name in the gazetteer, a zone with `majorRadius` 32,768 in the cache, and a
shape on a 1024×512 image — three independent handles on one thing.

**The fourth handle is in the pack and encrypted.** Each `<World>Icons.wpak` carries a 49th entry,
`ZoneDataENGLISH.cfg`, which is ciphered exactly like `Config.wpak`'s entries. Judging by its name
and its 41 KB it is the per-world zone table — plausibly the very thing that would put a zone at a
point on these images. Noted rather than opened; see the cameo note under *Not provided*.

### maps/terrain/ — the elevation, and the transform that places it

`python tools/export_terrain.py`. `terrain/` already held the 20,912 blend masks — how the
ground textures *mix*. This is the other half: the elevation of the ground they mix across.

This README used to say "all 14 continent heightmaps resolve in Textures.cache — not yet
extracted". That undercounted it. **178 zones name a heightmap and all 178 resolve**, from
128×128 for Uthgaard to 1024×384 for the Khar Thale Islands. They share 43 distinct images
between them, so the whole set is 6.7 MB rather than the ~40 MB a per-zone copy would cost.

An image alone is a picture. What makes it terrain is in the zone's `terrain_gen` record
next to it, which nothing had read either, and `terrain.json` carries it per zone:

```
y = minY + (grey / 255) * (maxY - minY)          # elevation
unitsPerPixelX = xSize / width                    # ground footprint
```

`terrain.json` records `unitsPerMetre` and `unitsPerMetreSource` alongside, because the
metre column depends on a scale that is itself measured and has moved twice.

`minY`/`maxY` read **0 and 800 on all 178**, so the greyscale ramp spans 0–800 world units
= **0 to 308 m** at 2.5994 units/m. That is this world's ceiling on terrain elevation. The
Dalgoth Marches image tops out at 202/255, so its highest ground is about 244 m.

| zone | image | px | footprint | units/px |
|---|---|---|---|---:|
| The Dalgoth Marches | 1005813 | 512×384 | 98304 × 73728 | 192 |
| Khar Thale Islands | 1005400 | 1024×384 | 65536 × 24576 | 64 |
| Vorringia | 1005821 | 448×512 | 57344 × 65536 | 128 |

Three things are flagged per zone rather than smoothed over:

- **`squarePixels: false` on 2 zones.** Units-per-pixel is clean (64/100/128/192)
  everywhere except `Tyrranth Major` and `Macrozone Test Continent`, both 450×360 over a
  65536×49152 footprint — 145.6 across against 136.5 down.
- **`source`** says whether the record was 8-bit or a 24-bit texture the red channel was
  taken from. 42 of the 43 images are 8-bit single channel. `1004000` (Kharduun, Plain of
  Ashes) is 24-bit but still a height field: its channels are equal on 639 of 784 sampled
  pixels and never differ by more than 1, which is lossy compression on something authored
  greyscale. `maxChannelDelta` records the loss.
- **13 zones are `PLANAR`** — no image, just a `flatHeight`. Listed under `flat`.

**Do not upscale these.** `1005400` and `1005813` are already sitting in `textures_2x/` as
Lanczos upscales, which is right for art and wrong for a height field: it invents
elevations between samples and softens coastlines.

---

## content/ — the part a wiki scrape can't match

`packages/tools/src/cli/import-content.ts` currently derives character data from
the Morloch Wiki XML, and its own header argues *"provenance matters more than
convenience."* This is that same mechanical data read out of the shipped client.

| File | Rows | Contents |
|---|---:|---|
| `races.json` | 33 | base + cap attributes, creation cost, health/mana/stamina, movement speeds, sex variants, eligible classes |
| `classes.json` | 27 | attribute adjustments, granted skills, skill adjustments, eligible races |
| `disciplines.json` | 48 | requirements, granted powers, rune category |
| `talents.json` | 240 | requirements and grants, **which are player-selectable**, rune category, attribute floors, applied effects |
| `items.json` | 4,021 | equip slot, weight, value, **damage**, weapon speed and range, level/rank requirements, race/class restrictions |
| `structures.json` | 1,062 | **two record types**: 294 buildable templates with a rank ladder, 768 named structures. See below |
| `powers.json` | 1,465 | cost, target, area, cast time, prerequisites, the ACTION chain, and every message string |
| `effects.json` | 2,950 | what a power *does*: mods, conditions, animation overrides, and who applies it |
| `rules.json` | — | movement speeds, recovery rates, the 305 scaling curves, 84 mod types, 94 skills |

Aelfborn, for instance: creation cost 5, base `Str 40 / Dex 50 / Con 40 / Int 45 /
Spi 35`, caps `95 / 120 / 95 / 105 / 85`, 24 eligible classes.

**Diff these against the wiki-derived tables rather than swapping outright.**
Where they disagree the cache is authoritative, but a disagreement is itself
worth understanding before overwriting anything.

### races.json agrees with the wiki on every number

`python tools/check_races_wiki.py`. One of two comparisons out of the five that found
nothing wrong; the other three turned up a misnamed field, a column empty on all 4,021
rows, and requirement lists that were inverted. Read this one as evidence about races
specifically rather than about `content/` generally — it passes on the pre-restrict-fix
export too, as the section on requirements below explains.

| | |
|---|---|
| creation cost | **12 / 12** |
| base attributes | **60 / 60** |
| attribute caps | **60 / 60** |
| eligible classes | **167 / 167** |

`Category:Races` holds exactly the twelve races `races.json` flags `standard_creation`,
which independently confirms that flag. So the 33 rows are 12 playable races plus 21
creature families (Animal, Construct, Dragon, Insect, Undead, Siege…), and the flag
separating them is right.

Two false alarms on the first pass, both the comparison's fault rather than either source's,
and both now handled in the tool: four pages write the attribute as a wiki link (`40 Base
[[Strength]]`), which reported 0/5 for those races; and the wiki wraps long class lists with
`<br>`, which read as a `<br> Prelate` entry and held the class match at 154/167.

### classes.json agrees too, and from the other direction

`python tools/check_classes_wiki.py`, over the 26 pages in `Category:Class`:

| | |
|---|---|
| base-class links | **31 / 31** |
| eligible races | **99 / 99** |
| granted skills | **69 / 69** |

This is not a restatement of the race check. That one validates **race → class** from the
race pages; this validates **class → race** from the class pages. The same relation read
from opposite ends, agreeing both ways.

`classes.json` carries 27 rows to the wiki's 26 — the extra is `Pet`, a rune type rather
than a player class, so it is expected rather than a discrepancy.

A third parser trap here, and the best one: **`Wear Armor, Medium` is a single skill whose
name contains a comma.** Splitting the wiki's comma-separated skill list cuts it into
`Wear Armor` and `Medium`, neither of which matches anything, and it reported 64/74. The
cache had it right throughout.

`items.json` carries equip slots, which is the field that lines up with the
`EquipSlot` values `@aegisfall/sim` already stores per character.

### structures.json is two tables, and the templates had no names

**Re-take `structures.json` too.** It holds two disjoint record types and every row was
missing the other one's columns:

- **294 templates** — the buildable city assets. They carry the `template_*` fields and the
  rank ladder (rank, health, hirelings, buildings) and have **no name at all**.
- **768 structures** — the things those ranks put down. Named, with floors, doors and
  health, and no ranks.

No row has both, so a reader filtering on `ranks` or on `name` silently gets one half of the
file. Every row now carries `kind`, either `"template"` or `"structure"`.

The templates shipped `name: ""` — 294 rows with no way to tell a Tree of Life from an Orc
Slave Pen. Their identity is in the buildings their ranks put down, and **all 294 now
resolve**: 285 reference exactly one named structure, and the nine that reference several
are progressions worth seeing in order — template 2000000 runs *Tree of Life → Belligerent
Palace → Feudal Palace → Mercantile Palace*, which is a city tree upgrading. The names are
in a new `building_names`, in rank order.

`health` at the top level stays empty and that is honest: `combat_health_full` reads 0.0 on
all 768 structures that carry it and is absent on the templates. The per-rank `health` is
the real one and always was.

**The wiki cannot check this.** Of the 250 distinct buildable structure names, **7** exist
as wiki pages, and most of those are lore or mechanics articles. Exactly one — *Tree of
Life* — carries a rank table, and its health ladder (80,000 → 500,000) does not match ours
(3,000 → 25,000 on the template that builds it). With a single comparable page there is no
way to tell patch drift from a mis-join, so it is recorded as unresolved rather than
counted either way.

### items.json shipped an empty damage column, and the wiki is how it was found

**Re-take `items.json` if you have an older copy.** It advertised `damage` and shipped
`[null, null]` on **all 4,021 rows**. `export_content.py` was reading `item_min_damage` and
`item_max_damage`, which are not fields any item has — the real numbers sit in a nested
`item_weapon` record as `weapon_damage`, a list of `{damage_type, damage_min, damage_max}`.
**785 of the 811 weapons now carry damage**, with the type on each entry (SLASHING 291,
CRUSHING 252, PIERCING 212, and a tail of BLEEDING, POISON, SIEGE, COLD, FIRE, MENTAL,
LIGHTNING, HOLY). The same record yielded `weapon.speed` and `weapon.maxRange`, which were
also being dropped.

Nothing internal could have caught this. An always-null column is perfectly self-consistent,
passes every completeness check, and reads as "this cache does not record damage". It took
an outside source quoting `8 - 34` for a weapon this export had nothing for.

Once the failure mode was known it was worth sweeping for: every column of every
`content/` table was checked for being empty on every row. Six more turned up, and **all six
are genuine zeros** — `item_rank_req`, `item_level_req`, `rune_creation_cost` on classes and
disciplines, `rune_pracs_per_level` on disciplines and talents. The keys exist on the
records and the values are zero in this build, which is a different statement from the
`damage` case and is why they are left alone. `damage` was the only wrong key.

`python tools/check_items_wiki.py` is that comparison, over the 264 pages in the wiki's
`Category:Weapons`, 229 of which name an item we have:

| field | compared | exact |
|---|---:|---:|
| damage min | 206 | 102 |
| damage max | 206 | 97 |
| weight | 221 | 130 |
| attack speed | 202 | 86 |

**Read the exact-match count as a floor, not a score.** Roughly half of each field matches
and the rest differs with *no single scale factor* — the wiki-to-cache ratio is 1.0 far more
often than anything else and the remainder is scattered. That is patch drift, the wiki
documenting a different build. A genuinely wrong field agrees ~0% of the time, which is
precisely what this reported before the fix.

One decoding note for anyone reading the raw records: attribute deltas are
stored unsigned, so −10 arrives as `4294967286`. The exporter converts these.

### Race and class requirements were inverted, and `[]` did not mean what it looked like

**Re-take `items.json`, `disciplines.json` and `talents.json`.** The requirement records in
the cache are `{restrict, races}` / `{restrict, classes}`, and the earlier export read the
list while ignoring the flag beside it. The flag *inverts* the list:

| stored | meaning | this export now emits |
|---|---|---|
| `restrict: false`, list | the list is who **may** | that list |
| `restrict: true`, list | the list is who **may not** — everyone else may | everyone else, resolved |
| `restrict: true`, empty | nothing excluded, so **anyone** may | `null` |
| `restrict: false`, empty | an empty allow-list, so **no one** may | `[]` |

Two consequences for anything already consuming these files:

**The lists were backwards.** Not incomplete — reversed. 619 items had their race list
inverted and 56 their class list, along with most disciplines. A discipline restricted
*away from* three races was published as available to *only* those three.

**`null` and `[]` are now different, and the old files only had `[]`.** Unrestricted is
`null`; an empty allow-list is `[]` and genuinely means nobody. The old export emitted `[]`
for both, on 3,177 of 4,021 items — so a consumer reading `[]` as "no race may equip this"
was locking players out of most of the item table, and one reading it as "no restriction"
was right by accident 3,177 times and wrong 3 times. Treat `null` as "no restriction" and
`[]` as "nobody"; only three items carry the latter (Lightning Spear, Alchemist's Cowl,
Alchemist's Robes).

The universe an exclusion resolves against is this export's own contents — the 12 races
flagged `standard_creation`, and the classes excluding `Pet`.

`python tools/check_disciplines_wiki.py` is the comparison that found it. Honouring the
flag takes discipline race agreement from **41/171 to 171/171** and class agreement from
**175/214 to 214/214**; every requirement on all 48 discipline pages now agrees.

Worth knowing if you are relying on the other checks: `check_races_wiki.py` and
`check_classes_wiki.py` score identically — and perfectly — on both the broken export and
the fixed one. 26 of the 27 class runes store `restrict: false`, where the naive read and
the correct read happen to agree, so **two perfect scores were being reported over a field
that was backwards on 675 rows**. Passing checks constrain only what they cover.

### talents.json gains six columns, and only 92 of its 240 rows are pickable

**Re-take `talents.json`, `disciplines.json` and `classes.json`.** The wiki documents
several things about a rune that the export simply did not carry, all of them present in
the cache the whole time:

| new column | what it is | rows (talents) |
|---|---|---:|
| `standard_creation` | **whether a player may pick this at all** | 92 of 240 |
| `rune_category` | the mutual-exclusion group — only one `Blood Gift` may be taken | 187 |
| `attribute_requirements` | the stat floor, e.g. Ambidexterity needs Dex 50 | 62 |
| `applies_effects` | passive effects the bearer gets, keyed into `effects.json` | 46 |
| `power_grants` | powers the rune teaches, keyed into `powers.json` | 97 |
| `rank` | `rune_rank` | 47 |

The first is the one to act on. `talents.json` mixes 92 player-selectable traits with
**148 NPC runes** — `Archer Mob`, `Belgosch Lord`, `Aelfborn Trainer` — in one table, and
nothing distinguished them. A creation screen built from the old file would have offered
`Anti-Tank Boss Mob` alongside `Agile`. Filter on `standard_creation`.

15 talents store an unresolved string hash where the category name belongs; those carry
`rune_category_hash` instead. It resolves against nothing in the client's hash table or in
this export, so it is preserved rather than dropped.

**Key `talents.json` by `asset_id`, not by name.** Five names carry two rows each with
different data: `Proficient with Axes`, `Proficient with Daggers`, `Proficient with
Hammers`, `Witch Sight` and `Wizard's Apprentice`. In every case the wiki matches the lower
id and the higher is a stripped duplicate — `Proficient with Daggers` 250083 requires
Healer where 250125 requires nothing.

Two joins are worth knowing about:

`applies_effects` names a **power action**, not an effect. Most action ids happen to equal
the effect they apply, which is why most tokens resolve straight against `effects.json` —
but 19 do not (`TRT-TIRELESS` applies `TIRELESS`). `powers.json` now carries the full
`actions` table for exactly this reason; resolve a rune token through it first and fall
back to `effects.json`. With it the join is 231/231.

And **194 effects carry a placeholder where their display name should be** — `MOVE-B-5%
"MOB" 0` and `RES-MAGIC-B-5 "TALENT" 0` are what `Effects.cfg` literally contains. That is
the client's own data, not a parse error. Read an effect's meaning from its `mods`, not
its `name`.

`python tools/check_talents_wiki.py` compares against `Starting Traits` (the 85 player
traits) and `Statistic Rune` (the 35-row stat ladder): **407 of 408 fields agree**, with
creation cost, rune category, attribute floors, granted attributes, skill grants and
adjustments, and race and class requirements all exact. The one difference is the wiki
giving `Blood of the Dragon` a movement bonus the record does not have — checked against
the raw COBJECT, not just the export.

### powers.json / effects.json — the part the wiki has least of

The wiki lists about 460 powers. This is **all 1,465**, read out of the decrypted config
rather than scraped, plus the 2,950 effects they apply. `python tools/export_powers.py`.

They are one chain, and each file carries the join already resolved:

```
Powers.cfg  --ACTION=-->  PowerActions.cfg  --applies-->  Effects.cfg
```

so a power lists the effect ids it ends up applying, and an effect lists the powers that
apply it (`appliedBy`) and the actions that name it (`namedByActions`). The two differ:
2,908 effects are named by some action but only 1,294 by an action a power lists directly
— the rest are reached indirectly, mostly as the deferred half of a `DeferredPower`.

`powers.json` also carries the **middle link itself** as a top-level `actions` table, all
3,046 of them, which it did not before. Resolving it only per-power left every action no
power lists unreachable — and runes reach effects through exactly those. See the talents
section above.

**`IsItemEffect` marks 717 of them**, which is most of the answer to why an effect has no
power: it comes from an item proc. Only **42** effects are reachable from nothing at all.

Both files are checked against the source rather than assumed complete: every one of
Powers.cfg's 41 keys is accounted for line-for-line, and Effects.cfg's 13,427 content lines
map to exactly 13,427 exported records.

**Three authoring bugs in the shipped config are reported, not repaired**, under
`problems`: a `POWEREND= COSTAMT SL0050Up` that writes a key onto a block terminator and
loses it; `SRDX-DB`, whose header repeats its kind/skill/name triple and so has 25 fields
instead of 22; and `PRL-033`, whose cast time reads `2.9.0`. A power with a bad header
keeps its tokens under `headerUnparsed` rather than getting mislabelled fields.

**Three of the five unnamed header fields now have names, and two still do not.**
`Powers.cfg` names none of its 22 positional fields and the client parses them into unnamed
struct slots (`sb.exe` 0x56e410), so every name here is evidenced from the data —
`areaRadius` is non-zero on exactly the powers whose `areaShape` is not `NONE`, and so on.

| field | what the evidence says |
|---|---|
| `unused12` | 0 on all 1,464 well-formed powers. Parsed, stored, never varied. |
| `unused13` | 0 on 1,463; one power reads 10.0. Dead in this build either way. |
| `recycleSeconds` | was `unknown16`. **A cooldown, not a duration** — equals the wiki's *Recycle Time* exactly on 322 of the 389 powers named in both. 0 on 562 powers means "not stated here". |
| `requiresHitRoll` | was `unknown17`. Matches the wiki's *Requires Hit Roll* on 384 of 389, and is never set where the wiki says no. |
| `unknown15` | 0.0 (788), 1 (568), 0.1 (68), 0.5 (29), 2.4 (8), 5.0 (3). Matches nothing in the data and nothing the wiki records. |

**Two of these names were fixed by checking against the wiki, and one of them was wrong.**
`recycleSeconds` shipped briefly as `durationSeconds`, on the reasoning that its values are
canonical second-counts clustered by category — 20.0 on every WEAPON power, 3600 on
*Fortress of Faith*. That is equally true of a cooldown, which is what it is. No amount of
internal consistency was going to catch it; an outside source did, in one pass.

`python tools/check_powers_wiki.py` is that comparison, and it is worth re-running after any
change to the header names. It reports agreement per field:

| wiki field | ours | agree |
|---|---|---|
| Target and Range | `target` | **140 / 140** |
| Requires Hit Roll | `requiresHitRoll` | 384 / 389 |
| Power Type | `kind` | 376 / 382 |
| Focus Skill | `skillName` | 339 / 353 |
| Recycle Time | `recycleSeconds` | 322 / 389 |
| Target and Range | `range` | 208 / 232 |
| Area of Effect | `areaRadius` or `range` | 74 / 93 |
| Stamina Cost | `costAmount` | 28 / 29 |
| Mana Cost | `costAmount` | 255 / 348 |
| Casting Time | `castSeconds` | 67 / 388 |

**`Area of Effect` looks like a failure and is not one.** Read as a radius throughout it
agrees on 39%. The wiki uses that heading for two different quantities: on a power whose
`areaShape` is `NONE` it is quoting the *range*. Split by shape it lands exactly on 74 of
93, and the remainder is drift between the wiki's patch and this cache — it says 32 where
the cache says 30. Both `areaRadius` and `range` come out validated.

**Casting time is the interesting disagreement.** The wiki reports exactly one second more
on 225 powers — 215 of them `SPELL`, 217 MANA-cost — and agrees exactly on 67, mostly the
0.2 s instant melee ones. A fixed extra second on spells, cause unestablished. The cache is
what shipped, so `castSeconds` carries the config's own figure; if you are matching player
recollection of cast times, add the second.

The wiki lists 438 named powers to the cache's 1,163 distinct names, 389 of which appear in
both. `powers.json` carries all of this as `headerFieldNotes` and `checkedAgainst`, so it
travels with the data.

**`effects.json` has no equivalent check, and that is the source's doing rather than an
omission.** The wiki has no per-effect pages: `Category:Powers` holds the class lists plus
seven mechanics pages (Buff, Stun, Summon, Tracking, Invisibility, Skill, Traveling
Stance), and its `Effect(s)` field appears on **five** powers in total, carrying prose about
stacking rather than anything joinable. The 2,950 effects are checked against their own
source instead — `export_powers.py` accounts for every one of Effects.cfg's 13,427 content
lines — and indirectly by the table above, since those power fields are what the
power-to-effect join is built on.

`animIdA`/`animIdB` are ANIMIDs that resolve through `animations/resolve.json`; together
with `loopanimid` they are set on 674 powers, 529 of the 560 that cast for 2 s or more, so
they are the phases of a cast. Which starts and which finishes is not established, so they
are not named as if it were.

### rules.json — the tables powers.json refers to but does not contain

`python tools/export_rules.py`. Four small configs nobody had read, and one of them changes
what the other exports are worth.

**`curves` resolves the scale tokens.** `powers.json` and `effects.json` are littered with
`SL0083Up`, `SL1500Up`, `SIVL0205` — on `HateValue`, on `MeleeDamageModifier`, on `ACTION`
— and they could only be handed over as opaque strings. `CompoundCurves.cfg` defines all
305 of them, so the combat numbers become computable:

```
Cleave → effect "Axe" → MeleeDamageModifier 16.8 SL0083Up
       → +16.8 damage, +0.83 per level, over a range of 100
```

The four digits are hundredths — `SL0083Up` is 0.83, not 0.083 — which is the sort of thing
to read out of the table rather than infer from the name. **232 curve tokens are used across
powers and effects and all 232 resolve**, checked on every run.

**`modTypes` names the verbs.** 84 rows giving each mod in `effects.json` its behaviour and
the label the client shows: `MeleeDamageModifier` → *"Damage"* (Combat, Standard),
`OCV`/`DCV`, `ArmorPiercing`, `Block`, `AttackDelay`.

**`skills`** — 94 skills with the attributes that drive each one and their weights
(`Axe = Intelligence 60, Strength 40`), plus the client's own description text.

#### Movement, in metres

`speeds` is world units per second, with metres alongside at the units/m `reference/summary.json` measures — 2.5994 as of the joint-frame fix, read at run time rather than pinned:

| | units/s | m/s | km/h |
|---|---:|---:|---:|
| WALK | 6.50 | 2.50 | 9.0 |
| RUN | 14.67 | 5.64 | 20.3 |
| COMBATWALK | 4.44 | 1.71 | 6.1 |
| COMBATRUN | 14.67 | 5.64 | 20.3 |
| SWIM | 6.50 | 2.50 | 9.0 |
| FLYRUN | 18.38 | 7.07 | 25.5 |

**Combat mode costs you your walk and leaves your run alone.** The file also keeps the
previous tuning commented out above the live values (`WALKSPEED 6.88`, `RUNSPEED 15.52`),
captured as `supersededUnitsPerSecond` — the world was deliberately slowed.

These are defaults: `races.json` already carries per-race overrides and those win. An
Aelfborn runs 13.97 against the default 14.67; an `Animal` runs 22.93.

`recovery` completes the movement picture — regeneration is *seconds to recover 1 percent*
for health and mana and *seconds per point* for stamina, and it is zero while running.
Running costs 0.4 stamina/second out of combat and 0.65 in it, so a chase is bounded by
stamina rather than by speed.

## reference/ — scale

`dimensions.json` / `.csv` give world-space size, footprint, part and triangle
count per asset; `summary.json` adds per-category percentiles.

| Category | median W × H × D (units) | ≈ metres |
|---|---|---|
| Structure | 52.4 × 32.9 × 57.0 | 20 × 13 × 22 |
| Prop | 5.0 × 4.4 × 3.8 | 1.9 × 1.7 × 1.5 |
| Item | 0.5 × 1.2 × 0.4 | 0.2 × 0.5 × 0.15 |
| Creature | 3.4 × 5.6 × 3.9 | 1.3 × 2.2 × 1.5 |

Only the creature row moved when the joint frame landed — nothing else on this page is
posed, so structures, props and items are the same numbers as before at a slightly
different metre scale.

### The scale changed, and the old number was measured wrong

**`units_per_metre` is 2.5994, basis Human.** It was 2.903, then 2.7411. Three
corrections, and the third is the largest:

1. **Sizes now include `obj_scale` and `rune_scale_factor`.** Neither had ever been read.
   `rune_scale_factor` takes 74 distinct values from 0.8× to 2.0× across all 2,380 creatures —
   it is how one body mesh serves a goblin and a giant — so every creature figure written before
   now was the unscaled base mesh, and they were all effectively the same height.
2. **The yardstick is a person, not the bestiary.** With scaling applied, the median of all
   creatures reads 5.579 units, which would put the world at 3.10 units/m — but that median spans
   dragons. Measured against the twelve playable races instead:

| | units | |---| | units |
|---|---:|---|---|---:|
| Dwarf | 3.880 | | Centaur | 5.701 |
| **Human** | **4.679** | | Minotaur | 6.521 |
| Shade | 4.006 | | Nephilim | 4.430 |
| Aelfborn | 4.932 | | Aracoix | 4.649 |

Human is the one 1.8 m actually describes, so it leads. The playable-race median is 5.049
and the all-creature median 5.579, reported alongside for context rather than used.

3. **The pose it was measured from was wrong, and the feet are why.** Every one dropped 4–5% when the
   ASF joint frame landed, because the figures had been measured off a body leaning ~13°
   backwards. The Aracoix dropped 8.685 → 4.649 — its wings had been standing above its
   head, and folded down its back it measures what a Human measures, which is what a
   humanoid body should. Widths rose 40–50% for the same reason: limbs are where they
   belong instead of collapsed against the torso.

   **The mechanism is the toes.** The cache's rest pose runs every limb straight down its
   axis, so the foot points at the floor like a ballet en pointe — `LFOOT` reads
   `(0, -1, 0)`. Posed correctly it lies flat, `(0.16, -0.01, 0.99)`, and the bottom of the
   bounding box rises 0.310 units. That is the whole of the Human's 0.255 drop, and it is
   the right direction: a person's height is measured flat-footed, not on their toes.

   Telling detail: **the old published figure, 4.934, is exactly the rest-pose height** —
   for the Dwarf too, 4.055 against 4.055. Whatever the old stance was doing, it was not
   moving the extremes of the box it was measured from.

   **The Minotaur is the control.** It is the one playable rig whose stance comes from the
   rest pose rather than a clip, so the joint frame cannot touch it — and it reads 6.521
   before and after, unchanged to three decimals. That is what says the rest geometry is
   untouched and every other move here came from applying clips correctly.

One trap found on the way: the source ships most races twice, `2011_Human` and `2012_Human`, a
male body and a female one. A plain name lookup keeps whichever came last and measures the Human
at 4.192 instead of 4.679. Lowest asset id wins, matching the choice Aegisfall's `stage-bodies.ts`
already made for the same reason.

**Anything baked at 2.903 is ~11% off and anything baked at 2.7411 is ~5.2% off** —
including `unitsPerMetre` in Aegisfall's `structures/`, `weapons/` and `world/` manifests.
This figure has now moved twice; it is derived from a measurement of a posed model, so it
will move again if the pose does. `content/rules.json` and `maps/terrain/terrain.json` read
it out of `reference/summary.json` at run time for that reason, and record which source
they used.

If you author buildings to these proportions, siege distances, door heights and
camera framing land where a shipped MMO put them.

### Buildings and trees, weighted by what the world actually places

The whole-catalogue medians above include assets nobody uses. Joining `dimensions.json` to
`zones/required_models.json` gives the sizes the world is actually built from:

| | distinct | placements | p5 | median | p95 |
|---|---:|---:|---:|---:|---:|
| Structures | 310 | 2,844 | 1.4 m | **8.9 m** | 24.8 m |
| Props | 1,115 | 44,419 | 0.2 m | **1.6 m** | 30.0 m |
| Trees | 73 | 3,536 | 0.4 m | **18.9 m** | 74.0 m |

**Neither buildings nor trees carry a scale multiplier** — `obj_scale` is non-unit on 17 assets and
all of them are weapons, and `rune_scale_factor` is creature-only (2,028 of 2,380). So for a
structure or a prop the mesh envelope *is* the in-world size, and no correction applies.

**The furniture is what validates the metre scale**, because it is the category with an obvious
right answer:

| | units | at 2.5994 | at the old 2.7411 | expected |
|---|---:|---:|---:|---|
| Church Pew | 2.682 | 1.03 m | 0.98 m | ~0.9–1.1 m |
| Table | 2.008 | **0.77 m** | 0.73 m | 0.75 m standard |
| Floor Torch | 5.535 | 2.13 m | 2.02 m | ~2 m |
| Group of Bags | 1.398 | 0.54 m | 0.51 m | — |
| Fire Pit | 1.244 | 0.48 m | 0.45 m | — |

Furniture is unposed, so these units did not move — only the metre column did, and it is
worth showing both. The table is the tightest test here because a dining table is a
standardised 0.75 m, and 2.5994 puts it at 0.77 against the old figure's 0.73. The pew and
the torch are looser and sit comfortably either way. So the furniture backs the new scale,
though not by much, and it is a better check on it than the creature median that derived
it.

Buildings run larger than modern intuition and that is the genre, not an error: a `Stockade Tower`
is 8.5 m, a `Straight Outer Wall` 20.9 m, a `Concave Tower` 21.6 m. This is a siege game and the
walls are meant to be walked to.

**Trees have a deliberate long tail.** Median 18.9 m is an ordinary forest tree, but eight tree
props exceed 55 m and **all eight are placed** — up to one at 213 m used six times. No real tree
reaches that (a redwood tops out near 115 m), so those are landmark or backdrop trees rather than
scatter, and sizing your own foliage to the median would miss the silhouette they were for.

One thing to look at before copying proportions: ground scatter is authored large — `Fern` measures
3.3 m and `Grass` 1.5 m. Those are more likely clumps rendered as a single prop than a single plant,
which matters if you are matching density rather than size.

## models/

```
models/Structure/124100_Ardani_Library.glb
models/assets.json      # asset_id, name, kind, parts, textures, skeleton_id, file, bytes
```

| Category | Files | Size |
|---|---:|---:|
| Structure | 1,057 | 806 MB |
| Item | 4,018 | 168 MB |
| Prop | 1,564 | 193 MB |
| Deed | 880 | 12 MB |
| Other | 25 | 4 MB |
| Creature | 2,380 | 590 MB |

Loads with the `GLTFLoader` already in `packages/client/src/rigModel.ts`. Each
part is its own node with its own transform; base colour textures are embedded,
so a file is self-contained. Verified by round-trip — reloaded vertex counts
match the source records exactly and every material carries a `baseColorTexture`.

**408 assets have no geometry and were not exported.** That is correct, not a
gap: 315 are class/discipline/talent runes pointing at a null render, 68 are
weather/particle/sound stubs, 6 are lights.

### Creature rig caveat — read before planning around creatures

Your art packs share one **65-bone Unreal-standard rig** (`root`, `pelvis`,
`spine_01..03`, `neck_01`, `Head`, `clavicle`/`upperarm`/`lowerarm`/`hand`,
`thigh`/`calf`/`foot`), which is why the 86-clip library binds with no
retargeting.

**Shadowbane is not one rig — it is 103 of them**, 4,228 bones in total, now exported to `rig/`.
This section used to say "a 43-bone ASF-style rig", which was the humanoid one read from the only
skeleton the earlier export happened to write. The cache holds:

| skeleton | bones | shape |
|---|---:|---|
| 1 | 43 | humanoid — `ROOT`, `LHIPJOINT`, `LFEMUR`, `LTIBIA`, `LFOOT`, `LSHEATH` … |
| 2 | 44 | humanoid with `LTOE` |
| 3 | 27 | **quadruped** — `ULEG1`/`LLEG1` … `ULEG4`/`LLEG4` |

So "map Shadowbane's rig onto the Unreal rig" is a humanoid-only plan; a spider or a wyrm has a
body plan the Unreal skeleton has no joints for. Three.js binds tracks *by name*, so your clips
will not drive any of these models.

**1,037 bones carry a `flip` flag** — the mirrored-limb marker. Shadowbane ships one arm mesh and
mirrors it for the other side, so a rig read without that flag draws two left arms. It is in
`rig/skeletons.json` along with each bone's full 16-float bind pose, which the earlier export
also dropped.

Two further problems:

1. **Names differ.** A mapping is feasible and mostly obvious
   (`LOWERBACK`→`spine_01`, `LHUMERUS`→`upperarm_l`, `LFEMUR`→`thigh_l`), but
   Shadowbane has no finger chains and carries bones the Unreal rig lacks
   (`LSHEATH`, `BACKSHEATH`, `HELM`, `BEARD`).
2. **These are not skinned meshes.** Shadowbane attaches one rigid mesh per bone
   rather than skinning one mesh across a weighted skeleton. The GLBs bake each
   part at its bind-pose joint. Animating them means emitting a genuinely skinned
   mesh with vertex weights, or driving the part nodes directly.

Shadowbane's own **1,503 `.AMC` motion clips** are in `Motion.cache` and play on
the native rig with no retargeting at all — the cheaper path if the goal is
Shadowbane movement rather than reuse of the Quaternius library. **They are now
exported**, in full, as `motions/tracks/` — see the next section.

For reference use — proportion, silhouette, how a body was cut into parts — the
creature GLBs are fine as they are.

### 18 rigs are bound to no model, and one of them is a siege engine

`rig/` carries 103 skeletons. The creature catalogue binds 85. The other **18 are complete
rigs with clips, referenced by nothing in this build** — their bones are in
`rig/skeletons.json` and their clips are in `motions/tracks/clips/` already, so they are
available, just unused.

**Skeleton 52 is the interesting one: a wheeled siege engine.** 15 bones — a `BODY`
chassis, `WHEEL01` forward and `WHEEL02` behind, a `CRANK`, and a 9.03-unit `ARM` ending in
`RWRIST` → `RHELD`, which is the attachment point every rig in this cache uses for a held
object. Three clips, one per ANIMID band, which is how a simple non-humanoid rig is
authored:

| clip | slots | what moves |
|---|---|---|
| `52000001` | 1–8, 37 (movement) | **only the two wheels**, 12°/frame — a 30-frame loop |
| `52000010` | 10–61 (idle) | nothing; a single static frame, parked |
| `52000075` | 64–117 (attack, incl. 75/76 `powerActionAttack`) | `CRANK` a full revolution, `WHEEL02`, and the `ARM` |

The fire clip reads exactly like a catapult: the `ARM` snaps from +80° to +10° off vertical
in three frames (0.2 s) and `RHELD` travels from `(0, 2.94, −5.40)` to `(0, 9.68, +2.51)` —
low-and-behind to high-and-forward — then winds back down over the remaining 0.6 s and
loops.

The roll clip is internally consistent in a way worth checking against: 12° per frame is
exactly 360° over its 30 frames, so one revolution per 2.0 s. At the wheel's 1.359-unit
radius that is 3.29 m of ground per revolution, or **1.64 m/s** — about two thirds of the
2.50 m/s walk in `rules.json`, which is what a heavy machine being pushed should be.

Nothing in the cache binds it: zero assets across every kind, zero race runes. The wheeled
props that exist (`Elven Ballista`, `Wagon`, `Cart`) are static meshes with no skeleton at
all. So this is a rig authored for a siege engine whose model either never shipped or is
assembled server-side.

**Skeleton 122 is the other one worth a look: an eight-armed, four-legged body.** It reads
as a face rig from its first few bone names and is nothing of the sort. Each shoulder
carries one humerus which then branches into **four** forearms — `LRADIUS`, `LRADIUSA`,
`LRADIUSB`, `LRADIUSC` — and each of those has its own wrist, hand, finger and thumb. Eight
hands in total. Below, four hip joints carry four single-segment femurs with no tibia or
foot. It stands 8.55 units, **3.29 m**.

The four `FACE` bones are paired upper and lower appendages either side of the head —
mandibles rather than expression — and they are animated, in three separate clips.

Only the primary pair of hands carries weapon mounts (`LHELD`, `RHELD`, `LSHIELD`), so it
wields in two and has six free. It also carries the ordinary humanoid attachments: `HELM`,
`BEARD`, `HAIR`, and the three sheaths.

Unlike the siege engine, its clip set is rich — 8 clips, and `122000010` alone fills 233
ANIMID slots across idle, emote, parry, combat and weapon-swing at 88 frames:

| clip | frames | fills |
|---|---:|---|
| `122000001` / `122000002` | 14 / 23 | the movement band |
| `122000010` | 88 | 233 slots: idle, emote, parry, combatIdle, weaponSwing, powerLoop |
| `122000055` | 31 | one slot; moves the mandibles |
| `122000075` | 45 | attack, including `powerActionAttack` |
| `122000200` / `201` / `202` | 30 / 60 / 46 | three specials; `201` is a `powerLoop` channel |

Nothing binds it either. The obvious candidates do not fit — every spider in the catalogue
(and there are dozens) is on skeleton 27.

**Skeletons 111 and 112 are not new rigs at all: they are the male human with a different
death.** Bone-for-bone identical to skeleton 1 — same names, lengths, directions, axes and
parents — and identical to each other. 221 of their 231 clips are skeleton 1's own
(`1000xxx`), nine more are borrowed from 18, and each has exactly **one** clip of its own.
Their ANIMID tables differ from skeleton 1's in a single slot: **55**.

Slot 55 is the death animation. 88 of the 103 rigs fill it with a clip of their own, and
the shape is unmistakable — on skeleton 1 the spine goes from 12.9° off upright to **83.9°**
over 32 frames, which is a body ending flat on the ground. Rigs 6, 18, 54 and 112 all do
the same thing.

`111000055` does not. Over its 31 frames the spine stays vertical (87.3° → 87.4° above
horizontal), the arms and legs hang and straighten to point almost straight down (−80.6° →
−86.5°), the head tips back (neck 86.8° → 60.3°), and `ROOT` translates **upward** — 0.019,
0.110, 0.258, 0.443, 0.659 units, an accelerating lift rather than a fall.

A limp body rising vertically into the air. Whatever it was for, it is a death that
ascends instead of collapsing, and it is a distinct animation from both of the others —
all three differ in their rotation data, not just their frame counts.

So the useful reading is: `1000055` is the ordinary human death, `112000055` is a second
one that also falls, and `111000055` is the interesting one. All three drive skeleton 1's
geometry, so any of them can be played on a human model already in `models_rigged/` without
touching the rig.

A rig here is mostly a *clip table*, not a body. **Thirteen skeletons share skeleton 1's
bones exactly** — 1, 7, 9, 16, 98, 101, 102, 110, 111, 112, 120, 130, 131 — and differ only
in which clips their ANIMID slots point at. Most differ wholesale (rigs 9, 16, 98, 101,
102, 110, 130 and 131 differ from rig 1 in *every* shared slot, so they are separate
creatures wearing one skeleton). A few differ in almost nothing, and when they do, it is
the death:

| rig | shares bones with | slots differing | what changes |
|---|---|---:|---|
| 111 | 1 | **1** of 241 | slot 55 — rises into the air instead of falling |
| 112 | 1 | **1** of 241 | slot 55 — a second, ordinary fall |
| 61 | **50** (which *is* bound) | **1** of 103 | slot 55 — stays upright rather than going flat |
| 120 | 1 | 8 of 247 | a bound rig, listed for contrast |

So `61` is the same trick as `111`/`112` against a different body, and worth knowing about
if you want an alternate death without a new rig.

The remaining thirteen have geometry of their own:

| rig | bones | own clips | body |
|---|---:|---:|---|
| 3 | 27 | 7 | four legs, an **eight-segment neck** (`NECK1..8`) and a jaw — a long-necked beast |
| 42 | 23 | 8 | **no legs**: spine, two arms, jaw and a three-segment tail — serpentine |
| 46 | 33 | 11 | winged biped, three-segment wings, tail; 3.13 m across at rest |
| 40 | 35 | 7 | large biped with an extra hip segment, a three-part neck, a jaw and two `SPIKE` bones |
| 2 | 44 | 11 | humanoid with toes (`LTOE`/`RTOE`) — the standard 43-bone rig plus feet detail |
| 28 | 40 | 8 | humanoid with toes but simplified hands — no fingers or thumbs |
| 114 | 39 | 7 | humanoid with a jaw |
| 26 | 42 | **1** | a standard humanoid that borrows almost everything |
| 31 | 33 | 7 | humanoid with **ears** (`EARJOINT`, `LEAR`, `REAR`); arms stop at the radius |
| 33 | 25 | 5 | simplified biped — femur straight to foot, humerus straight to radius |
| 63 | 11 | 1 | minimal critter: two femurs, two humeri, head, tail |
| 57 | 4 | 1 | `ROOT`, `LWING`, `RWING`, `LOWERBACK` — a flier reduced to two wing bones |
| 32 | 2 | 7 | `ROOT` and `LOWERBACK`. Two bones, seven clips of its own |

#### Rig 32: two bones, 53 slots, and it dies belly-up

Worth a section because it is the smallest animated thing in the cache and it is fully
animated. `ROOT` plus one `LOWERBACK` running **13.9 cm** straight forward (`+Z`), and that
is the entire skeleton. It fills 53 ANIMID slots from seven clips of its own — movement,
idle, death, attack, the lot.

**`LOWERBACK` never rotates in any of them.** Every frame of every clip animates `ROOT`
alone, so the body is one rigid piece and the animation is the object's own motion through
space:

| clip | frames | what it does |
|---|---:|---|
| move | 16 | weaves side to side, ±0.11 units across while advancing, yaw swinging ±15° |
| idle | 17 | no translation; yaw drifts ±5° |
| attack | 7 | darts forward 1.73 units and back 0.98, pitching down 21° |
| death | 16 | **rolls 180° onto its back** |

The death is the tell, and it is measured rather than inferred: the body's up axis travels
from `(0, +1, 0)` to `(0, −1, 0)` while its forward axis stays on `+Z` the whole way, so it
rolls about its own long axis and settles inverted, wobbling between 177° and 179°. A
14 cm rigid body that weaves as it moves, darts to strike, and turns belly-up when killed.

What it was for is not established. The obvious candidates are all accounted for elsewhere:
beetles are on rig 36, crabs 60, rats 21 and 22, snakes and vipers 82, spiders 27, bats 8,
12 and 55. The only `Fish` in the catalogue is an item with no skeleton at all.

## motions/ and animations/ — the clips, and how to play one

```
models_rigged/Creature/2002_Aracoix.glb   the rig, at its REST pose, nodes named per bone
motions/tracks/clips/<token>.json         per bone, per frame, a quaternion
animations/index.json                     the manifest and the contract
animations/catalog.json                   assetId -> skeletonId + which GLB
animations/skeleton_actions.json          skeletonId -> action -> clip token + track file
animations/overrides.json                 what an ACTIVE effect plays instead of what
```

All 1,503 clips, 42.6 MB, at the source's own frame rate (1,483 clips at 15 fps, 20 at 120).
Absent bones are omitted and held at bind pose; a channel written `rot` is constant for the whole
clip, `rotFrames` is flat, four numbers per frame.

**The contract is four words: apply track bones to nodes by name.** Bind by name, never by index —
a rig carries bones no clip drives and clips name bones a rig lacks (6 cases, listed in
`index.json` under `problems`).

```js
const q = clip.bones[node.name];              // absent -> leave at bind pose
node.quaternion.set(q[0], q[1], q[2], q[3]);  // (x, y, z, w), parent-frame
```

### Powers change animations, and that link is now exported

A power does not name an animation directly. It names an ACTION, the action applies an
EFFECT, and the effect carries `AnimOverride <from> <to>` — *while I am up, play B where
you would have played A*. That is how a buffed character swings differently.
`animations/overrides.json` is that join, over 243 effects and 1,345 pairs.

It was missing, and it was hiding clips: **33 of the 39 target ANIMIDs are named by no
other source**, including the whole 400–420 run — **714 (skeleton, ANIMID) pairs**, every
one resolving to a track file already on disk. Worth re-reading your action list against
it if you built one before now.

### The rotations are parent-frame, and that is a change

The cache does **not** state rotations that way. It states each bone's rotation in that bone's own
*joint frame* — the frame its `axis` triple defines — and the client conjugates out of it,
`C · R · C⁻¹`, before composing anything. The export now does that conjugation for you, so a track
quaternion drops straight onto a node with no rig lookup and the four-word contract above stays
literally true.

Each clip file states which it is:

| field | meaning |
|---|---|
| `"rotationFrame": "parent"` | ready to apply — every clip a skeleton names |
| `"rotationFrame": "joint"` | **not** ready — conjugate it yourself, see below |

The 80 clips no skeleton references carry `"joint"`, because there is no rig to take the `axis`
from. If you play one, conjugate it against whichever rig you play it on:

```js
// axis is in rig/skeletons.json, per bone, radians, applied Z then Y then X
const C = quatFromEulerZYX(bone.axis);
q = C.clone().multiply(q).multiply(C.clone().invert());
```

**This fixed a real defect rather than moving one around.** Every clip we rendered leaned about
13 degrees backwards, because the joint frame was being ignored — the client's own skeleton setup
(`sb.exe` 0x5d78c0) reads the axis, builds `C` and `C⁻¹`, and hands each bone its parent's inverse,
which is textbook ASF. Against client video of the Aracoix idle the spine went from +13.3° off
vertical to −3.6°, and the wings stopped standing out horizontally and folded down the back.
`docs/CLIENT_BINARY_FINDINGS.md` sections 4 and 6 have the disassembly and the evidence.

### What that means for bundles already on disk

| bundle | state |
|---|---|
| `motions/tracks/` | **regenerated** — parent-frame, ready |
| `animations/` | **regenerated** — repackaged, 0 integrity failures across 85 rigs |
| `models_rigged/` | **unaffected** — it is the rest pose, which is what the tracks drive |
| `rig/` | **unaffected** — bind pose and `axis` were always right |
| `models/` (creature), `graph/`, `reference/` | **stale** — these bake a standing clip frame, so they carry the old lean. Regenerate before trusting creature *heights* or a posed creature GLB. |
| everything else | **unaffected** — no bundle outside these touches the pose |

```bash
python tools/export_assets.py --kind Creature --out export_aegisfall/models
python tools/export_graph.py  --all           --out export_aegisfall/graph
python tools/measure_assets.py                --out export_aegisfall/reference
```

Non-creature `models/` — structures, props, items, deeds, the 1.2 GB — never had a pose applied and
did not move.

## sounds/ and terrain/

- **sounds/** — 1,086 WAVs, 49.2 min, mostly 22050 Hz mono 16-bit. Records are
  raw PCM behind a 16-byte header; the declared length matched the payload on
  every record.
- **terrain/** — 20,912 128×128 greyscale blend masks: the weights the client
  used to mix ground textures. Every record matched the expected header exactly.

Both counts equal what
[ShadowbaneCacheExporter](https://github.com/pmeade/ShadowbaneCacheExporter)
reports, which is independent confirmation they decoded correctly rather than
merely self-consistently.

## icons/, icons_png/ and effects/

- **icons/** — `atlas_0..6.png` at 4096², 84.4% fill, alpha preserved.
  `atlas.json` gives per-icon `asset_id`, `name`, `kind`, `texture_id`, `page`,
  `x/y/w/h` — enough to draw an inventory grid from one texture.
- **icons_png/** — the same art as **8,377 individual PNGs**, foldered by
  category and named `<id>_<name>.png`, with `icons.json` as the index. More
  than the atlas's 6,081 because it also carries the **2,296 rune class crests**
  (`--class-icons`), which the atlas leaves out; 4,251 catalogue entries own no
  icon at all and are reported rather than counted as failures. 51 MB in 8,377
  files averaging 6.4 KB — `du` will say 81 MB, which is block rounding on a lot
  of tiny files rather than bytes you have to move.

  | | Creature | Item | Deed | Structure |
  |---|---:|---:|---:|---:|
  | files | 4,991 | 2,016 | 854 | 516 |

- **effects/** — `tiles.json` (9 tile-set records, pairs with the terrain blends)
  and `visuals.json` (480 records, 2,015 particle/lightning/geometry components
  with durations). Every record parsed and was consumed to the last byte;
  anything only partly understood would be flagged `fully_parsed: false`.
- **effects/textures/** — **the art those effects draw with**, which
  `visuals.json` names only by ID. 132 distinct textures across 2,843
  references, every one present in `Textures.cache` and decoded: PNGs named
  `<id>.png` with `index.json` ordering them by how many effects use each. 2 MB.

  Mostly 128×128 (93 of 132) with a few 256² sheets and some 256×32 strips for
  lightning. The two most-used — texture `1` at 360 effects and `3` at 323 — are
  the soft radial glows almost every particle system is built from.

  A particle system is a texture plus a curve, and the bundle previously shipped
  only the curve. Regenerate with `python tools/export_effects.py --textures`.

## config/ — the encrypted config archives, opened

**200 `.cfg` files that were Blowfish-encrypted and are now readable**, including `Powers.cfg`
(1,465 powers), `Effects.cfg`, and the three per-world `ZoneDataENGLISH.cfg`.
`python tools/decrypt_wpak.py --all`.

**Blowfish in CFB with an 8-byte block, fixed key, all-zero IV:**

```
key  85 71 40 3c 14 50 0b 52 73 2d 10 08 63 59 5b aa
iv   00 00 00 00 00 00 00 00
c[i] = p[i] XOR E(c[i-1])
```

The mode fell out of one observation: a keystream derived from a single known plaintext banner
decrypted the *first 8 bytes* of all 140 entries and nothing further — universal block 0, per-file
blocks after, which is CFB and only CFB.

**The key is not in any binary, and 419 million candidates proved it the hard way.** Byte windows
at 13 lengths across every DLL and EXE, then every address the code points at, all came back empty
— because `sb.exe` builds the key on the stack one byte at a time:

```asm
0x0054dee2  mov  byte ptr [ebp-0x20], 0x85
0x0054dee6  mov  byte ptr [ebp-0x1f], 0x71     ; ... 16 stores, never adjacent in the file
0x0054df39  push 0x10                          ; key length
0x0054df3e  call ArcBlowfishEncryption::ctor
```

Found by disassembly instead: the Blowfish P-array constant `0x243F6A88` has exactly one reference
in `.text`, which sits in the key-schedule routine, whose single caller is reached through an
incremental-link thunk, whose caller is the code above. **Search cost ~20 minutes of compute and
found nothing; reading the code cost four steps.** Worth remembering the next time a key looks
brute-forceable.

One detail for anyone reusing this: the key schedule clamps length to `0x48` = **72 bytes**, not
Blowfish's usual 56, so a stock library will refuse keys this client would accept.

### What it did *not* contain

- **`Powers.cfg` names no icons.** 1,465 powers, and zero occurrences of `cam`, `CAMEO`, `ICON`,
  `.tga` or `.png`. The guess that decryption would yield the power→cameo mapping was wrong; the
  wiki is the only source for that, and always was.
- **`ZoneDataENGLISH.cfg` carries no coordinates.** It is `<ZONENAME>`, `<ZONELORE>`, `<MINLEVEL>`,
  `<MAXLEVEL>` — 55 zones for Aerynth, 54 for Dalgoth, 38 for Vorringia. Authoritative level bands
  and lore straight from the client, but **it does not place a zone on a continent**, so the
  zone-to-continent question is still open.

What it *is* worth: 1,465 powers against the 460 the wiki lists, and 147 zones with client-authored
level bands to check the wiki-derived gazetteer against.

## cameos/ — the power icons, and the only bundle not from the cache

195 round per-power icons, `raw/` at their native 28×28 and `64/` upscaled, with `index.json`.
`python tools/fetch_cameos.py --names <list> --size 64`.

**They are not in the client, and that is established rather than assumed.** `D-131` recorded it;
a later exhaustive search confirmed it:

| looked in | result |
|---|---|
| `Textures.cache` — 4,730 unclaimed square textures scored for circular content | 24 hits, every one a shield or a glow sprite |
| `Skins/Default.zip` + `Login.zip` — 1,250 TGAs | window borders, bars, camera buttons |
| all 11 `*.wpak` archives | only the three `Maps/*Icons.wpak` are unencrypted |
| `*ENGLISH.txt` string tables (UTF-16, readable) | names only, no image references |
| `Skin.dll`, `Core.dll`, `Shadowbane.exe`, `sb.exe` | no embedded TGA/PNG |
| every file in the install, grepped for `cameo` / `cam.tga` | **zero hits** |

The client names them and ships none of them, so they come from the wiki the names point at.
Requests are spaced 0.4 s and cached files are never refetched.

**Six had to come from the Wayback Machine.** `Backstab.png`, `Buchinine.png`, `Galpa.png`,
`Gorgons.png`, `Magusbane.png` and `Pellegorn.png` 404 on the wiki today — they are also the only
six that break the `X cam.png` naming convention, which is likely why they were the ones lost.
Wayback never captured MediaWiki's `Special:FilePath` redirect, only the direct `/images/…` URLs
pages embed, and MediaWiki derives that path from the **MD5 of the filename**: `Backstab.png`
hashes to `7a7a…`, hence `/images/7/7a/Backstab.png`. Verified against all six, so the fallback
generalises to any file the wiki loses later. Wayback throttles bursts, so it backs off — a rate
limit is not a missing file, and treating it as one silently reported five of the six as gone.

**Upscale with Lanczos, not nearest.** Nearest is the textbook choice for small pixel art and 28→56
is an exact 2×, but a cameo is an anti-aliased circle: nearest stair-steps the rim visibly, while
Lanczos carries the existing edge softening through. Checked by rendering both, not by reasoning
about it.

## Not provided

- **Neural texture upscale** — on hold. `textures_2x/` holds CPU Lanczos
  upscales; given Aegisfall is authoring its own textures, this is dead weight
  and I'd skip the folder entirely. Two zone heightmaps (`1005400`, `1005813`)
  are in there by accident and should be taken from `maps/terrain/` instead —
  upscaling a height field invents elevations between samples.
  *(Zone heightmaps used to be listed here as unextracted. All 178 are in
  `maps/terrain/`.)*
- **Thumbnail contact sheets** — tool exists, not delivered. It ran at 4.9 s per
  asset; three fixes are applied but unmeasured, so treat it as unfinished.
  *(Motion clips used to be listed here. All 1,503 are exported — see
  `motions/tracks/`.)*
- **Palette / Dungeon caches** — 512 bytes each, genuinely empty in this build.
  Nothing was missed. This is also why paletted textures cannot be resolved: the
  palettes are not shipped.
*(The `.cfg` cipher used to be listed here. It is solved — see `config/` above.)*

## Regenerating

```bash
python tools/export_assets.py         --all --out export_aegisfall/models
python tools/export_content.py              --out export_aegisfall/content
python tools/export_powers.py               --out export_aegisfall/content
python tools/measure_assets.py              --out export_aegisfall/reference
python tools/build_icon_atlas.py      --all --scale 2 --page 4096 --out export_aegisfall/icons
python tools/extract_sounds.py              --out export_aegisfall/sounds
python tools/extract_terrain_alpha.py --all --out export_aegisfall/terrain
python tools/export_effects.py --textures   --out export_aegisfall/effects
python tools/extract_icons.py  --class-icons --out export_aegisfall/icons_png
python tools/export_zones.py                --out export_aegisfall/zones
python tools/export_maps.py                 --out export_aegisfall/maps
python tools/export_terrain.py              --out export_aegisfall/maps/terrain
python tools/export_rules.py                --out export_aegisfall/content
python tools/fetch_cameos.py --size 64 --names <list>  --out export_aegisfall/cameos
python tools/decrypt_wpak.py --all           --out export_aegisfall/config
python tools/export_graph.py --all           --out export_aegisfall/graph
python tools/export_skeletons.py             --out export_aegisfall/rig
```

The animation bundle is four steps and they are ordered — `rig/` supplies the bone names and the
joint axis that the tracks are built against, so it goes first:

```bash
python tools/export_skeletons.py                        --out export_aegisfall/rig
python tools/export_assets.py --kind Creature --hierarchy --rest-pose                                                         --out export_aegisfall/models_rigged
python tools/export_motion_tracks.py                    # --> motions/tracks
python tools/export_animation_table.py                  # the ANIMID tables
python tools/package_animations.py                      # catalog, per-rig actions, index.json
```

`export_motion_tracks.py` writes each clip once even though 558 of the 1,423 tokens are named by
more than one skeleton. That is safe rather than assumed: rotations are conjugated by the naming
rig's joint axis, and `axis` is *not* a function of bone name — 95 of the 540 distinct names differ
between rigs — but no clip in this cache is ever shared between two rigs that disagree about a bone
it animates. The tool checks that on every run and names the clip and both rigs if it ever fails.

Full model export ~2 minutes; everything else seconds. Every tool takes
`--sample N` for a test run first.

Regeneration needs the original caches. Six of the thirteen were missing from
`arcane_dump/` for most of this work — their `.ver` stamps were present without
the archives, which made a missing-file problem look like a decoding gap. They
came from `C:\Code\Shadowbane - Throne of Oblivion\cache\`; keep that path
reachable.
