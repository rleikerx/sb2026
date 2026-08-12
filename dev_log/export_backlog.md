# Export backlog — completeness sweeps

The `content/` tables and the 147 config archives have been swept field-by-field against
what the exporters actually read. **The asset bundles have not**, and this file tracks that.

The method that worked for `content/`: for each bundle, ask what it *references* and
whether every reference resolves. A bundle that is internally consistent can still be
missing everything a consumer needs, and an always-empty column looks exactly like a
correct one. Nine defects this pass were of that shape.

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
- [ ] `Guild_Restrictions.*` (57 near-identical per-server files) — export or document why not
- [ ] `RaceClassDiscTalents.cfg` — UID → English name table; useful for resolving tokens
- [ ] Text bundles (`Emotes.cfg`, `ToolTips.cfg`, `PassiveMessageText.cfg`, `XNames.cfg`) —
      decide in or out of "mechanical data only", and record the decision either way

## Needs a running client or server — not reachable by reading

- `unknown15`, and which of `animIdA`/`animIdB` starts a cast
- the wiki's +1 s casting-time offset on 225 spells
- the Tree of Life health ladder, and whether `TREEOBJECTID= 547` means anything
- `Blood of the Dragon`'s missing movement bonus
- five powers disagreeing on `Requires Hit Roll`
