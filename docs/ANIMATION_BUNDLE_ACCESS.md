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
#   {"fps": 15, "frames": 61, "bones": {"ROOT": {"rotFrames": [...], ...}, ...}}
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

## What is verified

Checked by `package_animations.py` on every run, recorded in `index.json`:

- 2,380 GLBs ↔ 2,380 catalog rows, exact 1:1, nothing unmatched either way
- 85 rigs, all with a slot table and an action map
- 4,420 resolved action clips, **every one with a track file on disk**
- bone-name binding spot-checked on all 85 rigs: every clip-driven bone a rig
  actually owns is a node in its GLB — 0 failures across all 2,380 models
- 1,423 reachable clip tokens, 0 missing from the source cache
- the access flow above is executed against this bundle, not just written: it
  applies 28 bone rotations to `12050_Aracoix_Outcast` with 0 unmatched names
- clip rates are stated per clip — 1,483 at 15 fps and 20 at 120, none at 30

The baked set in `models/` is the other path: pose fused into geometry, cheap to
instance, **not drivable**. Use `models_rigged/` for anything animated.
