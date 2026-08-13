# Game integration spec — models, rigs, animation, combat props, summons

What a client needs to draw a character, dress it, animate it, and give it a pet.
Every number here was read out of `export_aegisfall/` on 13 Aug 2026; the commands
that regenerate each bundle are at the bottom.

**Bundle state as of this writing:** the data layer passed `loop.ps1` with no regressions,
and `graph/` was rebuilt on the fixed pose — all 9,924 assets reconcile exactly against
`reference/dimensions.json`.

This is the *consumer* view. `export_aegisfall/README.md` is the producer view — what
each bundle is and how it was decoded. Where the two disagree, re-run the tool and
trust the bundle.

---

## 0. The six ids, and which one you actually hold

Nearly every integration bug in this project has been one id used where another was
meant. There are six, and they are not interchangeable.

| id | lives in | means | resolves through |
|---|---|---|---|
| **assetId** | everything | a COBJECT — an item, creature, prop, structure | it *is* the filename key |
| **renderId** | `graph/assets/*.json` | the geometry an asset draws | `graph/assets`, `parts[].renderId` |
| **meshId** | `graph/assets/*.json` | one rigid mesh | `graph/meshes.json` |
| **textureId** | `graph/assets/*.json` | one bitmap | `graph/textures.json`, `textures_2x/<id>.png` |
| **skeletonId** | `models/assets.json` | which of the 103 rigs | `rig/skeletons.json` |
| **ANIMID** | powers, emotes, items | a *slot number*, not a clip | `animations/resolve.json` |

**assetId ≠ renderId.** This is the one that bites. 914 of 4,011 items render a mesh
that is not their own id — 292 weapons and 219 armour pieces among them. Hand Axe
`19011` draws render `19452`; every crossbow variant draws one of five shared meshes;
both Small Shields draw `182030`.

**ANIMID is not a clip id.** It is an index into the skeleton's own animation table,
and each rig fills its slots from its own clip namespace. `bow` is ANIMID 137 for
everyone; on a human that is clip `1000137`, on a minotaur whatever that rig put in
slot 137. This indirection is why one config drives 103 body plans, and why
`rig/skeletons.json` cannot be indexed by ANIMID (it drops zero entries, so the list
is compacted and every position after the first hole is wrong).

---

## 1. Models

```
models/<Kind>/<assetId>_<Name>.glb          9,924 files
models/assets.json                          the manifest
models_rigged/Creature/<id>_<Name>.glb      2,380 — one node per bone, at REST
graph/assets/<id>_<Name>.json               90,596 parts: mesh, texture, joint, transform
```

| Kind | files | size |
|---|---:|---:|
| Structure | 1,057 | 806 MB |
| Item | 4,018 | 168 MB |
| Prop | 1,564 | 193 MB |
| Deed | 880 | 12 MB |
| Creature | 2,380 | 590 MB |
| Other | 25 | 4 MB |

`assets.json` per row: `asset_id, name, kind, parts, skipped_parts, textures,
skeleton_id, pose_layer, pose_clip, file, bytes`.

**Files are self-contained.** Each part is its own node with its own transform, base
colour textures are embedded, and a round-trip check matched vertex counts to the
source records exactly. `GLTFLoader` opens them with nothing else on disk.

**408 assets have no geometry and were deliberately not exported** — 315 class /
discipline / talent runes pointing at a null render, 68 weather / particle / sound
stubs, 6 lights. Absence there is correct, not a gap.

### Use graph/ when you need the parts, models/ when you need the file

`models/` gives you a finished GLB. `graph/assets/<id>.json` gives you the assembly
that produced it, which is what you need to swap a texture, attach a part to a
different bone, or dedup geometry across items:

```jsonc
// graph/assets/19011_Hand_Axe.json
{ "assetId": 19011, "name": "Hand Axe", "kind": "Item",
  "skeletonId": null,
  "renderIds": [19452],                    // not 19011
  "parts": [
    { "meshId": 19455, "textureId": 19002, "joint": "RHELD",
      "renderId": 19452, "translation": [...], "basis": [[...],[...],[...]] },
    { "meshId": 19456, "textureId": 19009, "joint": "BLADE", "renderId": 19454, ... }
  ],
  "hardpoints": [ { "type": 3, "id": 36438017, "pos": [...], "rot": [...], "scale": [...] } ] }
```

### `basis` is row-major, and two scale factors sit outside it

Reconstructing a part's world position from `graph/` needs three things the file does not
spell out. Getting any of them wrong produces a plausible number rather than an error:

```js
// basis is ROW-major: row i is the image of local axis i.
const y = B[1][0]*x + B[1][1]*y0 + B[1][2]*z + T[1];   // correct
const y = B[0][1]*x + B[1][1]*y0 + B[2][1]*z + T[1];   // transposed — silently wrong
```

Then two multipliers, both outside the basis, and **both omitted from the JSON when they
are unit**:

| field | present on | range |
|---|---:|---|
| `runeScaleFactor` | all 2,380 creatures | 74 distinct values, 0.8–2.0 |
| `objScale` | **17 assets**, all weapons | 0.5 and 2.0 |

`objScale` is the one that hides — 17 files out of 9,924, so a sample of a few hundred
assets never sees the key and you conclude it does not exist. Kralla `189900` is 0.5×,
Throwing Hammer `25850` is 2.0×.

Bound a part by transforming **all eight** local AABB corners, not the min/max pair — a
rotated box's extent is not its rotated extent. With the row-major basis, all eight corners
and both scale factors, every one of the 9,924 assets in `graph/` reproduces its
`reference/dimensions.json` height exactly. Miss any one and you get near-misses that look
like rounding.

### Dedup is free and worth taking

Because 914 items share geometry with another item, a client that keys its mesh cache
on `renderIds` rather than `assetId` loads meaningfully fewer meshes than it has
items. 19 items share the crossbow meshes alone. Nothing about the file layout hints
at this — the filenames are all distinct — so it has to be done off `graph/`.

---

## 2. Meshes and textures

```
graph/meshes.json      19,862 meshes: verts, tris, uvs, min, max, size
graph/textures.json     5,128 textures: w, h, alpha
textures_2x/<id>.png    9,681 PNGs, Lanczos 2x
effects/textures/       133 particle textures
icons_png/              8,377 named icons  (also as 7 atlas pages in icons/)
terrain/                20,912 128x128 ground blend masks
maps/terrain/           178 zone heightmaps + the transform that places them
```

`graph/meshes.json` and `graph/textures.json` are **metadata only** — dimensions and
counts, no pixels, no vertices. They exist so a client can budget and size without
opening 1.2 GB of GLB. The actual bitmaps ship embedded in the GLBs (originals) and
standalone in `textures_2x/` (upscales).

**`textures_2x/` is upscaled art, and for height fields that is wrong.** Two of the
178 zone heightmaps (`1005400`, `1005813`) also sit in `textures_2x/`. Do not use those
copies — Lanczos invents elevations between samples and softens coastlines. Read
heightmaps from `maps/terrain/` only.

---

## 3. Skeletons

```
rig/skeletons.json     103 skeletons, 4,228 bones
rig/tables.json        colors, patterns, symbols, resources
```

Per bone: `name, nameHash, parent, length, flags, flip, direction, axis, bindPose`
(16 floats), `bindTranslation`.

**This is 103 rigs, not one.** Skeleton 1 is the 43-bone humanoid, 2 is a 44-bone
humanoid with `LTOE`, 3 is a 27-bone quadruped (`ULEG1`/`LLEG1`…`ULEG4`/`LLEG4`).
A spider or a wyrm has joints no humanoid rig has. Any plan that says "map Shadowbane's
rig onto ours" is a humanoid-only plan and needs a second answer for the other 102.

Skeleton 1, in order:

```
ROOT  LHIPJOINT LFEMUR LTIBIA LFOOT LSHEATHSPACER LSHEATH
      RHIPJOINT RFEMUR RTIBIA RFOOT RSHEATHSPACER RSHEATH
      LOWERBACK UPPERBACK NECKJOINT NECK HEAD HELM BEARD HAIR
      LSHOULDERJOINT LHUMERUS LRADIUS LWRIST LHAND LFINGERS LSPACER LHELD LTHUMB
      LSHLDSPACER LSHIELD
      RSHOULDERJOINT RHUMERUS RRADIUS RWRIST RHAND RFINGERS RSPACER RHELD RTHUMB
      BACKSHEATHSPACER BACKSHEATH
```

### Three properties you cannot skip

1. **`flip` — 1,037 bones carry it.** It marks a mirrored limb. Shadowbane ships one
   arm mesh and mirrors it for the other side; a rig read without this flag draws two
   left arms. On skeleton 1 the flipped set is exactly the left limb chain:
   `LHIPJOINT LFEMUR LTIBIA LFOOT LSHOULDERJOINT LHUMERUS LRADIUS LWRIST LHAND
   LFINGERS LTHUMB`. Section 6 shows what depends on this.

2. **`axis` — the joint frame.** The cache states bone rotations in the bone's own
   joint frame, and the client conjugates out of it (`C·R·C⁻¹`) before composing.
   `motions/tracks/` has already done this for you; the 80 clips no skeleton references
   have not, and are flagged (§5).

3. **These are not skinned meshes.** Shadowbane attaches one rigid mesh per bone
   rather than skinning one mesh across a weighted skeleton. The GLBs bake each part
   at its bind-pose joint. Animating them means either emitting a genuinely skinned
   mesh with vertex weights, or driving the part nodes directly. `models_rigged/`
   takes the second road: one node per bone, at rest, ready for tracks.

**18 rigs are bound to no model.** They decode fine and one of them is a siege engine.

---

## 4. Poses

Every creature GLB in `models/` is *posed standing*; every creature GLB in
`models_rigged/` is at *rest*. They are different files for different jobs — pose one
for a portrait or a measurement, rest one for animation.

`models/assets.json` says, per model, exactly how it was posed:

```jsonc
"skeleton_id": 115, "pose_layer": "upright+wingclip", "pose_clip": "1000219:12+wings 115000041:30"
```

`pose_clip` is `MOTION:FRAME`, so any pose in the bundle can be gone and looked at
rather than taken on trust.

| pose_layer | creatures | |
|---|---:|---|
| `upright` | 1,024 | biped, legs straight |
| `grounded+limbs` | 774 | four legs under the body |
| `rest` | 164 | no clip stands this rig; the cache's bind pose |
| `hunched` | 143 | biped that never straightens its legs |
| `grounded+limbs+wideleg` | 111 | arthropods |
| `upright+torso` | 74 | stance settled by the spine rung |
| `upright+wingclip` | 68 | wings read from a clip |
| `grounded+limbs+wingfold` | 18 | **wings authored by the exporter** |
| `upright+torso+wingfold` | 2 | likewise |
| `grounded` | 2 | grounded, forelimbs not settled |

**The 20 `+wingfold` rows are the only assets in this export whose pose is not wholly
the client's** — the Griffon and Nelchael families, whose wings no frame in this cache
folds. Everything else is a real frame from a real clip.

**The bind pose stands the figure on its toes.** The cache's rest pose points the feet
straight down, which is why every measurement is taken from a standing frame instead
(§10) and why `rest` in the table above is a fallback rather than a choice.

---

## 5. Animations

```
animations/index.json             the contract and the counts
animations/catalog.json           assetId -> skeletonId + which rigged GLB
animations/resolve.json           skeleton -> {animid: clipToken}   <- the key file
animations/skeleton_actions.json  skeletonId -> action class -> clip + track file
animations/actions.json           the ANIMID vocabulary by source
animations/items.json             item -> the ANIMIDs it selects + both render objects
animations/coverage.json          which (rig, action) pairs actually resolve
animations/overrides.json         what an ACTIVE effect plays instead of what
motions/tracks/clips/<token>.json 1,503 clips, per bone per frame
motions/tracks/<skeletonId>.json  the per-rig clip index
```

1,503 clips, 42.6 MB, at the source's own rate — 1,483 at 15 fps, 20 at 120.

### The contract is four words: apply track bones to nodes by name

```js
const q = clip.bones[node.name];              // absent -> leave at bind pose
node.quaternion.set(q[0], q[1], q[2], q[3]);  // (x, y, z, w), PARENT frame
```

Bind by name, never by index. A rig carries bones no clip drives, and clips name bones
a rig lacks — 6 such cases, listed in `index.json` under `problems`
(`12006_Water_Elemental` is the worst at 6).

A channel written `rot` is constant for the whole clip; `rotFrames` is flat, four
numbers per frame. Bones absent from a clip are absent from the file.

### Resolution is a two-step join

```js
const skeleton = catalog[assetId].skeletonId;
const animid   = items[weaponId].parryAnimId;      // or an emote, or a power
const clip     = resolve[skeleton].animid[animid]; // absent = this rig cannot do it
```

It is deliberately not materialised. Materialising it produces 5,110 rows that go
stale the moment a rig changes.

### rotationFrame — check it before you play

| field | meaning |
|---|---|
| `"rotationFrame": "parent"` | ready to apply — every clip a skeleton names |
| `"rotationFrame": "joint"` | **not** ready — the 80 clips no rig references |

For a `joint` clip, conjugate against whichever rig you play it on:

```js
const C = quatFromEulerZYX(bone.axis);   // rig/skeletons.json, radians, Z then Y then X
q = C.clone().multiply(q).multiply(C.clone().invert());
```

Ignoring this is what made every rendered clip lean ~13° backwards and held the Aracoix
wings out horizontally. Fixed; `docs/CLIENT_BINARY_FINDINGS.md` §4 and §6 carry the
disassembly.

### Coverage is uneven, and you must design for that

103 rigs, and almost none of them can do everything:

| action class | ids | rigs with ALL | mean resolved |
|---|---:|---:|---:|
| emote | 59 | **2** | 10.3 |
| powerLoop | 13 | 13 | 2.3 |
| powerActionAttack | 2 | 101 | 2.0 |
| parry | 7 | 15 | 1.0 |
| combatIdle | 12 | 100 | 11.7 |
| weaponSwing | 45 | 47 | 23.7 |
| animOverride | 39 | 15 | 9.1 |

A missing key means *this rig has no animation for that action* — it is data, not a
lookup failure. Fall back, do not throw.

### Powers change animations, and the link is exported

A power does not name an animation. It names an ACTION, the action applies an EFFECT,
and the effect carries `AnimOverride <from> <to>` — *while I am up, play B where you
would have played A*. `animations/overrides.json` is that join: 243 effects, 1,345
rows, 156 of which name two replacements for one slot.

**33 of its 39 target ANIMIDs are named by no other source**, including the whole
400–420 run — 714 (skeleton, ANIMID) pairs, every one resolving to a track file
already on disk. If you built an action list before this file existed, re-read it.

---

## 6. Weapons and armour

### Equip slots are bone names

| slot | items | | slot | items |
|---|---:|---|---|---:|
| CHEST | 537 | | RHELD | 362 |
| HELM | 519 | | RHELD+LHELD | 359 (two-handed) |
| FEET | 344 | | LHELD | 207 |
| LEGS | 300 | | HAIR | 184 |
| SLEEVES | 286 | | BEARD | 138 |
| HANDS | 247 | | RRING+LRING | 56 |
| — | | | AMULET | 55 |
| (none) | 427 | | | |

The slot is the *contract*; the actual attachment is per-part in
`graph/assets/<id>.json`, where each part names its own bone. A breastplate is not one
mesh on `CHEST` — it is two parts on `LOWERBACK` and `UPPERBACK`.

### Armour ships right-side only, and the rig mirrors it

This is the single most load-bearing fact in this section. Across all 3,172 weapons and
armour pieces:

| bone | parts | | bone | parts |
|---|---:|---|---|---:|
| LFEMUR | **0** | | RFEMUR | 415 |
| LTIBIA | **0** | | RTIBIA | 662 |
| LFOOT | **0** | | RFOOT | 346 |
| LHUMERUS | **0** | | RHUMERUS | 516 |
| LRADIUS | **0** | | RRADIUS | 513 |
| LHAND | **0** | | RHAND | 230 |
| LTHUMB | **0** | | RTHUMB | 232 |

Every paired limb bone has **zero** left-side parts. A greave is authored once, attached
to `RTIBIA`, and drawn on the left leg by mirroring through the `flip` flag on `LTIBIA`
(§3). A client that renders `parts[]` literally puts armour on one leg.

The `L*` joints that *do* carry parts are not left limbs: `LOWERBACK` (spine),
`LSHIELD`, `LHELD`, `LWRIST`, `LANCE`, `LBLADE`.

### Both meshes, and the female one is the only one that was ever exported

Items ship two meshes. Picking the male one for a female character is the same class of
mistake as picking the male skeleton.

- `content/items.json` → `render_object_female`, non-null on **1,380** items
  (960 distinct meshes)
- `animations/items.json` → `renderObject` **and** `renderObjectFemale`

`renderObject` was null on all 4,021 rows until 13 Aug 2026 — the exporter read
`obj_render_id`, an attribute that does not exist, and `getattr` returned `None` every
time. The real field is `obj_render_object`. Fixed; the table now carries a render
object for 4,011 of 4,011 items.

**Three `render_object_female` ids resolve to nothing** — no item record, no model file.
Fall back to `renderObject` for these:

| item | assetId | dangling female id |
|---|---:|---:|
| Nightstalker Leather Gloves | 5055240 | 5055340 |
| Nightstalker Leather Hood | 5055250 | 5055350 |
| Arch-Druid Cowl | 175120 | 178125 |

### Sheathing

72 rigs carry `LSHEATH`/`RSHEATH` (+`…SPACER`), 80 carry `BACKSHEATH`. 928 items are
`sheathable`, 804 of them weapons. The spacer bones exist so a sheathed weapon clears
the body; treat them as part of the chain, not as attach points.

### Which animation a weapon selects

`animations/items.json`, per item:

| field | weapons carrying it |
|---|---:|
| `parryAnimId` | 811 / 811 |
| `combatIdleAnimId` | 501 |
| `attackAnimRight` | 447 |
| `attackAnimLeft` | 314 |

`attackAnim*` is `[[ANIMID, weight], …]` and the weights sum to 100 — the client rolls a
weighted choice, it does not cycle them. Read flat, `64 33 66 33 67 34` invents an
ANIMID 33 that no weapon plays.

Parry concentrates hard: ANIMID 298 on 3,791 items, then 299 (80), 295 (38), 294 (35),
297 (30), 296 (29), 301 (18).

### Weapons have no skeleton and no pose

`skeleton_id` is null on all 4,018 item models; `pose_layer`/`pose_clip` are null too.
Items are static meshes hung on a creature's bones. The rig/frame machinery in §4
applies to creatures only.

---

## 7. Missiles and bolts

There is no missile *type* in this data. A projectile is an ordinary Item with its own
model, named by the weapon that throws it.

**100 of 811 weapons are ranged**, naming **28 distinct projectiles**, and every one of
the 28 resolves to a model in `models/Item/`:

| projectile | assetId | weapons |
|---|---:|---:|
| Arrow | 25650 | 39 |
| Arrow | 19090 | 15 |
| Crossbow Bolt | 19224 | 9 |
| Hurlbat | 25820 | 3 |
| Throwing Spike | 25870 | 3 |
| Storm Hammer | 25880 | 3 |
| Wing Axe | 29260 | 3 |
| Ring Blade | 29130 | 3 |
| Thunder Maul | 29150 | 3 |
| …19 more | | 1 each |

Flight comes from the weapon, not the projectile:

```jsonc
"weapon": { "speed": 26.0, "maxRange": 2.0, "projectileId": null, "projectileSpeed": null }
```

| | values |
|---|---|
| `projectileSpeed` | 50 (1), 55 (4), 66 (21), 75 (38), 100 (36) — world units/s |
| `maxRange` (ranged) | 20, 30, 40, 50, **125** (57 weapons), 150, 250, 500 |
| `maxRange` (melee) | 0, 2, 3, 4 (273 weapons), 6, 8 |

Divide by `unitsPerMetre` = 2.5994 for metres: a 125-unit bow reaches ~48 m, a 4-unit
melee weapon ~1.5 m.

**Throwing weapons name themselves.** Balanced Axe `19091` has `projectileId: 19091` —
the thing in flight is the thing in your hand. Bows do not: Composite Bow `19094` throws
Arrow `19090`.

Trails, impacts and glows are **not** here — they are in `effects/visuals.json`, 480 VFX
records, all fully parsed, made of 1,152 `PARTICLE`, 850 `GEOMETRY` and 13 `LIGHTNING`
effects. A particle effect carries `particle_attached_bone`, so a VFX binds to the rig
the same way a mesh part does.

---

## 8. Pets and minions

Three separate mechanisms, and only two of them are fully in the client data.

### Summoned — `CreateMob`, and the mob table is server-side

**21 powers summon**, through **343 `CreateMob` actions**:

| power | mob ids | power | mob ids |
|---|---|---|---|
| Craft Golem | 49, 50, 51 | Summon Phoenix | 60 |
| Craft Siege Golem | 3500 | Summon Genie | 61 |
| Summon Darkspawn | 52 | Summon Efreet | 62 |
| Weave of the Salamander | 53 | Summon Ice Fiend | 3501 |
| Weave of the Gnome | 54 | Conjure Familiar | 63, 64, 65 |
| Weave of the Undine | 55 | Call of the Dark Lords | 68 |
| Weave of the Sylph | 56 | Call to Vashteera | 70 |
| Cry of Vashteera | 57 | Harvest of Dust | 71 |
| Hunting Hound | 58 | Harvest of Bones | 72 |
| Call of the Sewers | 59 | Ithriana Summon Gaunts | 74 |

`CreateMob <mobId> <level>` — 25 distinct mob ids (49–74, plus 3500/3501), levels 8–75.
A power lists up to 20 of these, one per caster-level band, which is how one spell scales.

**`mobId` is not an assetId.** It indexes a mob table the client does not ship. You must
supply your own mapping from these 25 ids to creature models — the names above tell you
what each should look like, and the creature you want is almost certainly in
`models/Creature/`.

### Charmed — 23 powers, and the flags say what happens

```jsonc
{ "verb": "Charm", "args": ["CHARM", 1, "PetCharm"], "effects": ["CHARM"],
  "keys": { "levelcap": [14, "SL0065Up"], "isresistable": true,
            "clearaggro": true, "targetbecomespet": true } }
```

`targetbecomespet` is the flag that matters. Charm needs no model resolution at all —
the target is already drawn.

Powers: `BBN-002 BRD-004 BRD-005 BRD-011 BTY-003 COMMAND CON-021 CON-045 CON-047
DRK-003 DRU-044 JOE-001` and 11 more.

### Pet as a class

`classes.json` carries a **`Pet`** row (assetId 2522, `rune_type: CLASS`,
`rune_category: "Pet"`) — Con 120 base against a 2000 cap, Int and Spi pinned at 40 with
no headroom, granted `Dodge` and `Unarmed Combat` at 1. It is a rune type, not a player
class, which is why `classes.json` has 27 rows against the wiki's 26.

### What a mob actually looks like: runes, not templates

**Every mobile in the cache carries template `0`.** Identity is carried by rune stones
instead, and they resolve. From `zones/placements/`:

```jsonc
{ "label": "Father Keldran, Master Prelate", "level": 40, "respawnS": 120.0,
  "runes": [2111, 252597, 252620],
  "runeNames": ["Human Guard", "Master Prelate", "Shopkeeper"],
  "pos": [...], "yRot": 0.383972, "insideProp": 600400 }
```

**The race rune's assetId is the creature model id.** Rune `2111` → `animations/models.json`
gives `{race: "NPC", sex: "MALE", skeletonId: 1}` → `models/Creature/2111_Human_Guard.glb`,
posed `upright` off clip `1000219:12`.

That is the whole chain for any mob, pet or minion you can already see:

```
spawn.runes[0]  ->  models.json[rune].skeletonId  ->  rig + clips
                ->  models/Creature/<rune>_<Name>.glb        (posed, for display)
                ->  models_rigged/Creature/<rune>_<Name>.glb (rest, for animation)
```

2,380 race runes, 85 distinct skeletons, 2,243 male / 137 female. **Sex changes the
skeleton** — read it from `models.json`, never from `content/races.json`.

`renderable` in `models.json` is a boolean, not an id. The id you want is the rune key.

---

## 9. Emotes

59 emotes, ANIMID **130–185** contiguous plus **197, 198, 199**:

```
130 apologize  131 applaud   132 beckon    133 beg       134 blow      135 boast
136 bounce     137 bow       138 cackle    139 cheer     140 flip      141 chuckle
142 clap       143 cough     144 cower     145 cringe    146 chop      147 cries
148 dance      149 say       150 duck      151 faint     152 flex      153 flinch
154 perform    155 flip      156 fume      157 giggle    158 groan     159 grovel
160 howl       161 kneel     162 laugh     163 show      164 moo       165 moon
166 nod        167 peer      168 point     169 pray      170 preen     171 propose
172 puke       173 punch     174 rofl      175 salute    176 scream    177 shake
178 shiver     179 shrug     180 stagger   181 stretch   182 strut     183 give
184 wave       185 worship   197 shakefist 198 scary     199 letblood
```

Source is `Emotes.cfg`, joined into `animations/actions.json` under `actions.emote` and
into `skeleton_actions.json` per rig, which gives you the clip token and the track path
directly:

```jsonc
"emote": { "130": { "clip": 1000130, "track": "motions/tracks/clips/1000130.json",
                    "name": "apologize", "usedBy": null } }
```

**Only 2 of 103 rigs can play all 59**, and the mean rig resolves 10.3. Emotes are a
humanoid feature in practice. Build the UI off `coverage.json` per rig, or off
`skeleton_actions[skeletonId].actions.emote` directly — do not offer an emote wheel that
half the bestiary answers with a T-pose.

`140 flip` and `155 flip` are both named `flip` in the source. That is the config's
duplicate, not a decode error.

---

## 10. Scale, speed and units

**`unitsPerMetre` = 2.5994.** Read it from `reference/summary.json._scale_reference`,
do not copy it — it is derived from a *posed* model's height and has moved twice
(2.903 → 2.7411 → 2.5994). `content/rules.json` and `maps/terrain/terrain.json` read it
at run time and record `unitsPerMetreSource`.

Anything baked at 2.903 is ~11% off. **`tools/export_weapon_models.py` still hardcodes
2.903** to match `UNITS_PER_METRE` in `@aegisfall/core`; its header explains why, and it
is the one place in this repo that deliberately carries the old number.

Basis: the Human, measured standing, 4.679 units. Playable-race median 5.105.

| race | units | race | units |
|---|---:|---|---:|
| Dwarf | 3.880 | Aracoix | 5.044 |
| Shade | 4.653 | Irekei | 5.166 |
| Human | 4.679 | Elf | 5.168 |
| Vampire | 4.691 | Half-Giant | 5.351 |
| Aelfborn | 4.932 | Nephilim | 5.486 |
| | | Centaur | 5.701 |
| | | Minotaur | 6.521 |

Movement (`content/rules.json`, defaults — per-race overrides in `races.json` win):

| | units/s | m/s |
|---|---:|---:|
| WALKSPEED | 6.50 | 2.50 |
| RUNSPEED | 14.67 | 5.64 |
| COMBATWALKSPEED | 4.44 | 1.71 |
| COMBATRUNSPEED | 14.67 | 5.64 |
| SWIMSPEED | 6.50 | 2.50 |
| FLYWALKSPEED | 6.33 | 2.44 |
| FLYRUNSPEED | 18.38 | 7.07 |

Combat mode lowers the walk and leaves the run alone.

---

## 11. Known gaps — read before you file a bug

| gap | detail |
|---|---|
| 3 dangling female meshes | §6; fall back to `renderObject` |
| 10 items absent from the animation table | `580 581 627 628 629 630 631 632 633 637` — keys, blank keys and warrants. They are in `content/items.json` (4,021) but not `animations/items.json` (4,011); `cobject_rows` swallowed a parse failure. No combat relevance, but the counts will not match. |
| 6 rigs get tracks for bones they lack | listed in `animations/index.json.problems` |
| 80 clips are `rotationFrame: "joint"` | no rig references them; conjugate yourself (§5) |
| 18 rigs bind to no model | decode fine, one is a siege engine |
| 25 `CreateMob` mob ids unresolved | server-side table; you supply the mapping (§8) |
| 2 heightmaps have non-square pixels | Tyrranth Major and Macrozone Test Continent, 145.6 across vs 136.5 down |
| `models/` creatures may be stale | they bake a standing frame; re-run after any pose change |
| 2 textures do not resolve | `77000100` and `77000300`, reported by `export_graph.py` on every run |

---

## 12. Regenerating

Order matters in two places only — `rig/` before the motion tracks, and `reference/`
before anything that reports metres.

```bash
python tools/export_skeletons.py                        # rig/
python tools/export_assets.py --all                     # models/
python tools/export_assets.py --kind Creature --hierarchy --rest-pose \
                              --out export_aegisfall/models_rigged
python tools/export_motion_tracks.py                    # motions/tracks
python tools/export_animation_table.py                  # ANIMID tables + overrides
python tools/package_animations.py                      # animations/index.json
python tools/measure_assets.py                          # reference/   <- sets the scale
python tools/export_content.py                          # content/ races, classes, items
python tools/export_powers.py                           # content/ powers, effects
python tools/export_rules.py                            # content/ rules   <- reads the scale
python tools/export_terrain.py                          # maps/terrain    <- reads the scale
python tools/export_zones.py ; python tools/export_graph.py --all
```

After any pose change, three bundles bake a standing frame and must follow:

```bash
python tools/export_assets.py --kind Creature --out export_aegisfall/models
python tools/export_graph.py  --all           --out export_aegisfall/graph
python tools/measure_assets.py                --out export_aegisfall/reference
```

Look before you take:

```bash
python tools/serve_export.py     # http://localhost:8777/viewer/
```
