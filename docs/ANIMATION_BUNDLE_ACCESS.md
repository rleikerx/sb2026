# Aegisfall animation bundle

Rigged creature models, the motion clips that drive them, and the lookup that says
which clip plays for which action. Start at **`index.json`** — it names every file
here and states the contract.

Regenerate the whole thing with:

```
python tools/export_animation_table.py     # the ANIMID tables
python tools/package_animations.py         # the catalog, the per-rig actions, index.json
```

## The one idea you need

**An ANIMID is a slot number, not a clip id.** Every animation is chosen by an
ANIMID, and each rig fills its own slots from its own clip namespace. `bow` is
ANIMID 137 for everyone; on a male human that slot holds clip `1000137`, on a
female one `6000137`. That indirection is why one config drives every body plan —
and why you must resolve an ANIMID *through a specific skeleton*, never globally.

## Access, in five steps

```python
import json
from pathlib import Path

root    = Path("export_aegisfall")
catalog = json.loads((root/"animations/catalog.json").read_text())["catalog"]
rigs    = json.loads((root/"animations/skeleton_actions.json").read_text())["skeletonActions"]

# 1. find the model
row = catalog["12050"]                      # Aracoix Outcast
#   {"name": "Aracoix Outcast", "race": "NPC", "sex": "MALE",
#    "skeletonId": 18, "glb": "models_rigged/Creature/12050_Aracoix_Outcast.glb"}

# 2. load its GLB — bone nodes are already in it, no skins array, no weights
glb = root / row["glb"]

# 3. ask what that rig can do
rig = rigs[str(row["skeletonId"])]
#   rig["actions"] -> {"emote": {...}, "parry": {...}, "weaponSwing": {...}, ...}

# 4. pick an action; the key is the ANIMID
bow = rig["actions"]["emote"]["137"]
#   {"clip": 1000137, "track": "motions/tracks/clips/1000137.json", "name": "bow"}

# 5. load the track and drive the GLB's nodes BY NAME
track = json.loads((root/bow["track"]).read_text())
#   {"fps": 15, "frames": 47, "bones": {"ROOT": {"rotFrames": [...], ...}, ...}}
```

Applying a frame:

```python
f = 12
for bone, channel in track["bones"].items():
    node = nodes_by_name.get(bone.upper())   # match on name, case-insensitive
    if node is None:
        continue                             # see "Traps" — normal, not an error

    if "rotFrames" in channel:               # per-frame channel
        q = channel["rotFrames"][f*4 : f*4+4]
    else:                                    # constant for the whole clip
        q = channel["rot"]
    node.rotation = q                        # [x, y, z, w]
```

**Handle both channel shapes.** A bone that never moves in a clip is written once as
`rot` rather than repeated as `rotFrames`; reading `rotFrames` unconditionally raises
on the first such bone. This is not an edge case — **10,069 of 48,039 rotation
channels (21%) are constant**. `posFrames`/`pos` follow the same rule; in practice
only the root translates, every other bone sits at its rest offset and turns.

**Quaternions are `[x, y, z, w]`** — the same order glTF uses, so no reordering.
Bones absent from a clip should be held at their bind pose. Play at `fps` from the
file: it is the clip's own stated rate, **not** a constant — do not assume 30.

## Item-driven actions

`parry`, `combatIdle` and `weaponSwing` are listed per rig — *can this body plan
parry at all* is a real question — but **which** one plays is chosen by the equipped
weapon. `rig["itemDriven"]` names those classes. Go through `items.json`:

```python
items = json.loads((root/"animations/items.json").read_text())["items"]
axe = items["25030"]                    # Battle Axe
axe["parryAnimId"]        # 298
axe["combatIdleAnimId"]   # 12
axe["attackAnimRight"]    # [[64, 33], [66, 33], [67, 34]]
axe["attackAnimLeft"]     # [[65, 100]]

clip = rig["actions"]["parry"][str(axe["parryAnimId"])]["clip"]
```

Attack entries are `[animid, weight]` and the weights sum to 100 — the client rolls
a **weighted choice**, it does not cycle them in order.

## Files

| file | what it is |
|---|---|
| `index.json` | manifest: counts, file map, contract, integrity results |
| `catalog.json` | one row per rigged GLB — id, name, race, sex, rig, file path |
| `skeleton_actions.json` | per rig: every named action resolved to clip + track file |
| `items.json` | per item: the ANIMIDs it selects, and both render objects |
| `resolve.json` | raw per-rig slot table, `{animid: clipToken}`, uncompacted |
| `actions.json` | the ANIMID vocabulary by source |
| `models.json` | every model → rig, race, sex |
| `coverage.json` | per rig, how many ids of each class resolve |

`catalog` + `skeleton_actions` + `items` is all most consumers need. `resolve` and
`actions` are the raw inputs those two are built from.

## Reference — action classes

| class | ids | range | chosen by | source |
|---|---:|---|---|---|
| `emote` | 59 | 130–199 | player / AI | `Emotes.cfg` `ANIMID` |
| `weaponSwing` | 45 | 64–117 | equipped weapon | `weapon_attack_anim_right`/`_left` |
| `powerLoop` | 13 | 166–311 | power being cast | `Powers.cfg` `LOOPANIMID` |
| `combatIdle` | 12 | 12–25 | equipped weapon | `weapon_combat_idle_anim` |
| `parry` | 7 | 294–301 | equipped weapon | `item_parry_anim_id` |
| `powerActionAttack` | 2 | 75–76 | power action | `PowerActions.cfg` `ATTACKANIMS` |

**parry, by item count** — 294:35, 295:38, 296:29, 297:30, **298:3,781**, 299:80, 301:18

**combatIdle, by weapon count** — 12:124, 13:6, 14:4, 15:18, 16:43, 17:38, 19:29,
20:30, 21:76, 22:25, 23:15, 25:93

## Reference — emote ids

```
130 apologize  131 applaud   132 beckon    133 beg        134 blow
135 boast      136 bounce    137 bow       138 cackle     139 cheer
140 flip       141 chuckle   142 clap      143 cough      144 cower
145 cringe     146 chop      147 cries     148 dance      149 say
150 duck       151 faint     152 flex      153 flinch     154 perform
155 flip       156 fume      157 giggle    158 groan      159 grovel
160 howl       161 kneel     162 laugh     163 show       164 moo
165 moon       166 nod       167 peer      168 point      169 pray
170 preen      171 propose   172 puke      173 punch      174 rofl
175 salute     176 scream    177 shake     178 shiver     179 shrug
180 stagger    181 stretch   182 strut     183 give       184 wave
185 worship    197 shakefist 198 scary     199 letblood
```

`198 scary` and `199 letblood` are named but have no clip on any rig. 140 and 155 are
both `flip`; 154 `perform` and 157 `giggle` share one clip. Ids 166–168 (`nod`, `peer`,
`point`) double as power loop poses.

## Reference — power ids

13 loop poses cover all 666 powers, heavily skewed:

| ANIMID | powers | examples |
|---:|---:|---|
| 213 | 334 | Ancient Riddle, Annoint Blade, Antidote |
| 209 | 117 | Aid to the Injured, Awaken the Fallen |
| 205 | 79 | Amazon's Endurance, Beast Lord's Boon |
| 217 | 53 | Aspect Revelation, Balefume, Battlemind |
| 167 | 15 | Camouflage, Detect Hidden |
| 201 | 8 | Acid Spit, Banshee Scream, Energy Drain |
| 168 | 5 | Capture, Capture Prey |
| 303 | 4 | Hamstring, Snare |
| 311 | 2 | Fury of the Northmen, Whirlwind Attack |
| 166 / 208 / 302 / 308 | 1 each | Lore of the Forge / Vok-Maalra / Knavery / Blade Dance |

`powerActionAttack` is separate: ANIMIDs **75** and **76**, each at weight 50, on 30
transform-type power actions (`ASS-017A`, `BKM-004A`, `EPI-017A`…).

## Reference — rig coverage

The ten rigs below carry 1,251 of the 2,380 models; `coverage.json` has all 85.
A dash means the rig has no animation in that class at all.

| rig | models | emote | parry | idle | swing | power |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 315 | 57 | 7 | 12 | 45 | 13 |
| 9 | 178 | — | — | 12 | 45 | 1 |
| 8 | 166 | 4 | — | 12 | 45 | 1 |
| 50 | 143 | 1 | — | 12 | 45 | 6 |
| 6 | 100 | 57 | 7 | 12 | 45 | 13 |
| 12 | 80 | 1 | — | 12 | 6 | — |
| 54 | 74 | 57 | 7 | 12 | 45 | 13 |
| 98 | 73 | 1 | — | 12 | 45 | — |
| 10 | 64 | 1 | — | 12 | 6 | 1 |
| 13 | 58 | 1 | — | 12 | 45 | — |

Rigs 1, 6 and 54 are the playable-race bodies. **645 of 2,380 models can parry; 726
have a real emote set.**

## Reference — schemas

```jsonc
// catalog[assetId]
{ "name": "Aracoix Outcast", "race": "NPC", "sex": "MALE",
  "skeletonId": 18, "glb": "models_rigged/Creature/12050_Aracoix_Outcast.glb" }

// skeletonActions[skeletonId]
{ "models": 44, "slots": 455,
  "itemDriven": ["parry", "combatIdle", "weaponSwing"],
  "actions": { "emote": { "137": {
      "clip": 1000137, "track": "motions/tracks/clips/1000137.json",
      "name": "bow",        // emotes only
      "usedBy": null } } } } // powers: list of power names

// items[itemId]
{ "name": "Battle Axe", "baseName": "Battle Axe", "type": "WEAPON",
  "equipSlots": 4, "skillUsed": 2691863556,
  "parryAnimId": 298,
  "renderObject": 25030, "renderObjectFemale": null,
  // weapons only:
  "combatIdleAnimId": 12,
  "attackAnimRight": [[64,33],[66,33],[67,34]],   // [animid, weight%]
  "attackAnimLeft":  [[65,100]],
  "weaponSpeed": 25.0, "maxRange": 5.0 }

// motions/tracks/clips/{clip}.json
{ "name": "…", "frames": 47, "fps": 15,
  "secondsPerFrame": 0.0667, "seconds": 3.13,
  "bones": {
    "ROOT":   { "rotFrames": [x,y,z,w, …], "posFrames": [x,y,z, …], "scale": 1.0 },
    "LFEMUR": { "rot": [x,y,z,w] } } }        // constant — no rotFrames key

// resolve.skeletons[skeletonId]
{ "slots": 455,         // total, holes included
  "filled": 247,        // non-zero slots
  "distinctClips": 234, // filled minus aliases
  "animid": { "137": 1000137, "298": 1000298 } }

// models[assetId]
{ "name": "…", "race": "…", "sex": "MALE", "skeletonId": 18, "renderable": true }

// coverage[skeletonId][class]
{ "of": 59, "resolved": 57 }
```

A clip in more than one slot is the rig saying those actions look the same.

## Traps

**A track can name a bone the rig does not have.** Clips are shared across rigs, so
skeleton 1's clip list includes `18000007` from the Aracoix namespace, which carries
wing tracks to a rig with no wings. **Skip any track name with no matching node.**
That is normal and expected — it is also why binding is by name and not by index; an
index binding would silently apply the wing track to whatever bone sat at that slot.

**A missing action is data, not an error.** If `rig["actions"]["parry"]` is absent,
that body plan has no parry animation. Only 645 of 2,380 models can parry — the
playable-race rigs. Do not fall back to another rig's clip.

**Sex changes the rig, always.** No race that ships both sexes shares a skeleton
(male human is 1, female is 6). `catalog.json` already carries the resolved rig per
model, so use it rather than looking a race up by name. Items likewise ship
`renderObject` and `renderObjectFemale`.

**Mirrored parts have a negative-determinant node transform**, which reverses
triangle winding. Reverse the winding where the determinant is negative — glTF
requires this, but engines vary. Nodes carry `flip: true` in `extras` to mark them.

**There is no dodge animation.** Dodge is a skill and a combat modifier; it resolves
to a number, never to a clip.

**Weights, not ids.** In `attackAnimRight`, `attackAnimLeft` and power `ATTACKANIMS`,
values alternate `[animid, weight]`. `ATTACKANIMS= 75 50 76 50` is two animations at
50% each, not four animations — reading it flat invents an ANIMID 50 that nothing plays.

## What is verified

Checked by `package_animations.py` on every run, recorded in `index.json`:

- 2,380 GLBs ↔ 2,380 catalog rows, exact 1:1, nothing unmatched either way
- 85 rigs, all with a slot table and an action map
- 4,335 resolved action clips, **every one with a track file on disk**
- bone-name binding spot-checked on all 85 rigs: every clip-driven bone a rig
  actually owns is a node in its GLB — 0 failures across all 2,380 models
- 1,423 reachable clip tokens, 0 missing from the source cache
- the access flow above is executed against this bundle, not just written: it
  applies 28 bone rotations to `12050_Aracoix_Outcast` with 0 unmatched names
- clip rates are stated per clip — 1,483 at 15 fps and 20 at 120, none at 30

The baked set in `models/` is the other path: pose fused into geometry, cheap to
instance, **not drivable**. Use `models_rigged/` for anything animated.
