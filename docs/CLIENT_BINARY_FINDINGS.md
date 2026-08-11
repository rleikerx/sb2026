# CLIENT_BINARY_FINDINGS

What the shipped client binaries say about the skeleton and motion formats, read
directly rather than inferred from the caches.

> Source: `C:\code\lakebane` (Lakebane build). Nothing here is guessed — every claim
> below cites the byte offset, exported symbol, or literal string it came from, and
> the reproduction steps are at the bottom.

## 1) Module map

| file | size | what it is | symbols |
|---|---:|---|---|
| `sb.exe` | 21.1 MB | the game client | no exports; 209 source paths in strings |
| `DFEngine.dll` | 704 KB | Double Fusion engine (net, platform, download) | 116 mangled, none skeleton-related |
| `Math.dll` | 94 KB | **vector/matrix/quaternion library** | **222 exported, all named** |
| `Core.dll` | 270 KB | container/socket support | 1201 mangled |
| `AGC.exe` | 811 KB | Borland-built launcher shell (`CODE`/`DATA`/`BSS` sections) | — |

None are packed: entropy 6.5–6.7 across code sections, normal section naming.

**The source tree is named in `sb.exe`:** `C:\ArcanePrime\Main_Branch\Shadowbane\Source\`,
209 `.cpp` paths including `ArcSkeleton.cpp`, `ArcMotion.cpp`, `ArcRenderObject.cpp`.
This repo's `arcane/Arc*.py` classes are ports of those files, which is why the names
line up.

## 2) The format is Acclaim ASF/AMC

`sb.exe` contains the complete ASF/AMC keyword set as literal strings:

```
:ROOT   :BONEDATA   :HIERARCHY   :UNITS   :DEGREES   :MOTION
```

and the parser's own error text:

```
ASF: Can't find parent bone named: %s
ASF: Can't find child bone named: %s
<ArcMotion::LoadAMC> error reading line
```

So `Skeleton.cache` and `Motion.cache` are **compiled ASF skeletons and AMC motion**,
not a bespoke layout. That matters: ASF/AMC is a public documented standard, so the
bone record's `direction`, `length` and `axis` fields have specified meanings —
`axis` is the bone's local coordinate frame, and AMC motion is authored in it.

`:DEGREES` implies the authored ASF used degrees; the compiled cache stores radians
(wing bones read exactly 1.5708 = pi/2), so the compiler converted.

## 3) Math.dll — the exact conventions

`Math.dll` exports 222 named symbols under a `math::` namespace and is not stripped,
so the conventions can be read rather than guessed.

**Quaternion layout is `[w, x, y, z]` — scalar first.** From
`?MakeRotateX@Quaternion@math@@SA?AV12@M@Z` (rva `0x2930`):

```asm
fld   dword ptr [esp+8]        ; angle
fmul  dword ptr [0x1000e11c]   ; * 0.5
fld   st(0)
fcos
mov   dword ptr [eax+8],  ecx  ; y = 0
mov   dword ptr [eax+0xc], ecx ; z = 0
fstp  dword ptr [eax]          ; [0] = cos(angle/2)   <- w
fsin
fstp  dword ptr [eax+4]        ; [4] = sin(angle/2)   <- x
```

A rotation about X writes the cosine at offset 0 and the sine at offset 4, zeroing
8 and 12. Half-angle, standard.

**Euler triple order is Z, then Y, then X.** From
`?MakeTripleRotate@Quaternion@math@@SA?AV12@ABVVector3@2@@Z` (rva `0x2b80`):

```asm
mov  eax, dword ptr [edi+8]    ; v.z  -> call 0x10002990  (MakeRotateZ)
mov  edx, dword ptr [edi+4]    ; v.y  -> call 0x10002960  (MakeRotateY)
mov  ecx, dword ptr [edi]      ; v.x  -> call 0x10002930  (MakeRotateX)
```

with quaternion products between them. Call targets confirmed against the export
table: `0x2990` = `MakeRotateZ`, `0x2960` = `MakeRotateY`, `0x2930` = `MakeRotateX`.

So `q = Z(v.z) * Y(v.y) * X(v.x)`, equivalently the matrix product `Rz @ Ry @ Rx`.

**There is only one Euler path.** `?FromEuler@Quaternion@math@@SA?AV12@ABVVector3@2@@Z`
(rva `0x2aa0`) is nine instructions that tail-call `0x2b80` — `FromEuler` *is*
`MakeTripleRotate`. No competing convention to disambiguate.

Also present and worth knowing about: `Quaternion::FromAxisAndAngle`,
`Quaternion::ToEuler`, `Matrix4::FromEuler` / `ToEuler` / `FromQuaternion`,
`Transformation` (translation + rotation + scale), `math::SLERP`.

`Math.dll` is PE32 (x86) while the tooling here runs 64-bit Python, so it cannot be
called directly via `ctypes` from this repo — it has to be read, or hosted in a
32-bit process.

## 4) The joint frame: `bone.axis` is used, and here is the code that uses it

**Resolved.** `pose()` used to compose `parent * clip_quat` and never touch `bone.axis`.
That was the defect behind both the universal backward lean and the Aracoix wing fold.
The client reads the axis, and the function that does it can be pointed at.

`sb.exe 0x5d78c0` walks the skeleton once at load and, for every bone:

```asm
005d793f  lea   edx, [esi + 0x30]          ; bone->axis, raw radians from the parser
005d7977  call  dword ptr [0x1ab0764]      ; Quaternion::MakeTripleRotate(axis)  -> C
005d7982  mov   dword ptr [esi + 0x90], edx ;   stored at bone+0x90
005d79ca  call  dword ptr [0x1ab077c]      ; Quaternion::Inverse                 -> C^-1
005d79ec  mov   dword ptr [esi + 0xa0], ecx ;   stored at bone+0xa0
005d7a28  call  0x42690e                   ; recurse per child, passing &C^-1
```

`0x42690e` is an incremental-link thunk to `0x5d7ba0`, the recursive body. Its first act
is to store the quaternion it was handed -- *the parent's* `C^-1` -- at the child's
`bone+0xb0`, then compute that child's own `C` and `C^-1` and recurse. The root is seeded
with the identity at `0x5d7942` (`0x3f800000` = 1.0f into `bone+0xb0`, scalar-first).

So the runtime bone carries, per bone:

| offset | contents |
|---|---|
| `0x20` | `direction`, from the `DIRECTION` handler at `0x5d6470` |
| `0x2c` | `length`, from the `LENGTH` handler at `0x5d64b0` |
| `0x30` | `axis`, raw radians |
| `0x90` | `C` = `MakeTripleRotate(axis)` |
| `0xa0` | `C^-1` |
| `0xb0` | the **parent's** `C^-1` |

Caching `C_parent^-1` on the child is the giveaway. It is exactly ASF's
`rot_parent_current`, and it says the chain the client evaluates is

```
A_i = A_parent * C_parent^-1 * C_i * R_i
```

with the two constant factors precomputed at load. Composing world-space turns instead,
which is what `ArcSkeleton.pose` does, the same chain collapses to the conjugation

```
G_i = G_parent * (C_i * R_i * C_i^-1)          tip_i = start_i + G_i * direction_i * length_i
```

and that is `ArcBoneRecord.local_rotation`. A bone the clip does not name is unaffected:
`C * I * C^-1` is the identity.

**`direction` stays authoritative for geometry.** The alternative -- offsetting each bone
along its own local +Z, `A_i * (0, 0, length)` -- is identical for every bone satisfying
`C * (0,0,1) == direction`, and that invariant holds for every animated bone of every rig
checked *except* `WING02..05` on rigs 18/115/116 and `MANEJOINT` on rig 54. On those nine
it wrecks the rest pose, so it is wrong. Their `axis` is a copy-paste `(90, 0, 0)` that
does not describe their direction; the client conjugates by it regardless, and so do we.

**Why the earlier search read this family as a near-miss.** It was scored on
`pose_invariants.py`'s aggregate, which averages in `arm` -- a weak invariant -- over rigs
allowed to be genuinely hunched. The aggregate moves only 15.84 -> 12.17. The anchored
number moves 17 degrees.

## 5) Inside sb.exe: the ASF parser

`sb.exe` is 18 MB of `.text` with no exports and no symbols, but the ASF keyword strings
are each referenced exactly once, which pins the parser precisely. Imagebase `0x400000`.

| token | handler VA | token | handler VA |
|---|---|---|---|
| `:VERSION` | `0x5d5e6d` | `NAME` | `0x5d63e7` |
| `:NAME` | `0x5d5e89` | `DIRECTION` | `0x5d6415` |
| `:MOTION` | `0x5d5eba` | `LENGTH` | `0x5d648b` |
| `:UNITS` | `0x5d6001` | **`AXIS` (bone)** | **`0x5d64c3`** |
| `:ROOT` | `0x5d6045` | `DOF` | `0x5d6542` |
| `:BONEDATA` | `0x5d6069` | `ORDER` (root) | `0x5d61bc` |
| `:HIERARCHY` | `0x5d608d` | `AXIS` (root) | `0x5d6210` |

Three things read straight out of it:

**Per-bone `axis` is stored raw at `bone+0x30`, scaled to radians.** From `0x5d64c3`:
three floats are parsed, each multiplied by the angle-units factor at `[ebp-0x4c]`
(what `:UNITS angle deg` sets), then written to `[eax]`, `[eax+4]`, `[eax+8]` where
`eax = bone_struct + 0x30`. It is **not** converted to a matrix or quaternion at load
time, so whatever consumes it does so during pose evaluation.

**The root's `AXIS` and `POSITION` are parsed and discarded.** At `0x5d620f` and
`0x5d622b` the token compare is followed by `test al,al; jne <next line>` with no
handler body — matched, then dropped.

**`ORDER` is stored, and only at root level.** `0x5d61bb` parses it and calls through
`0x419042` / `0x40c09a` to keep it. The per-bone `AXIS` handler has no order handling at
all, so every bone shares the root's order.

What reads `bone+0x30` is **section 4**: `0x5d78c0` and `0x5d7ba0`, which turn it into the
`C` / `C^-1` / parent-`C^-1` triple the pose chain composes. Those live outside the ASF
text parser, which is consistent with the text loaders being dev-only paths -- the shipped
client reads `Skeleton.cache` and `Motion.cache` -- but the bone struct they fill is the
same one, so the offsets carry across. `<ArcMotion::LoadAMC>` is referenced from `0x5ba087`
and `0x5baca1` if that path is wanted.

Tooling: `tools/pe_reader.py` (section map, VA<->offset, xref search) and
`tools/disasm_sb.py` (disassemble at a VA, annotating `.data` string operands).

## 6) Resolved: the back lean and the Aracoix wing fold

Both were the same defect -- `pose()` ignoring the joint frame (section 4) -- and both
closed when it was applied. Two changes, which had to land together:

1. `ArcBoneRecord.local_rotation` conjugates every clip quaternion by its bone's frame,
   `C * R * C^-1`.
2. `ArcMotion` now reads the clip quaternion straight, `(w, x, y, z) -> (x, y, z, w)`,
   with no component swap and no per-bone special case.

**Why (2) had to come with (1).** The old reader swapped y and z for every bone *except
bone 0*, and that exemption was the tell. Most bones carry an axis of `(90, 0, 0)`, where
the conjugation also moves the vector part between y and z -- so the swap was a hand-fitted
stand-in for the missing conjugation. Bone 0 is the root, the one bone whose axis is zero
and which therefore needed no stand-in, which is exactly why it alone was exempt. Remove
the swap without adding the conjugation and the pose is 166 degrees out, which is what the
earlier "no remap at all" result was measuring.

Results, rig 18 (`18000010`, slot 10), against the client video:

| measure | before | after |
|---|---:|---:|
| spine off vertical | +13.3 deg | -3.6 deg |
| head off vertical | +13.2 deg | -3.7 deg |
| lowest wing-tip height | 87% of stature above the ankle | 28% |

The remaining -3.6 degrees is a slight *forward* lean and is not the original defect
inverted; whether it is authored posture or a further error is not settled.

**An independent check, not a fit.** The same math has to fold the Aracoix wings and leave
the Nephilim's spread -- the doc's own note from client video. It does: on rig 18 the wing
tips drop to 28% of stature with a lateral span of 0.61, while rigs 115/116 keep a span of
3.40. Nothing in the change is aimed at either rig. `images/pose_review/` and a side render
of `2002` at frame 0 show it directly.

Still true, and still worth not repeating:

| hypothesis | verdict |
|---|---|
| hidden bind matrix in the 36 skipped bytes per bone | zero on all 55 bones |
| wrong frame chosen | idle clip is static across all 238 frames |
| Euler order | XYZ/YXZ/XZY identical here; ZYX clearly wrong; client uses ZYX-composed = `Rz@Ry@Rx` |
| `direction` also in the joint frame | collapses the model entirely |
| handedness (negated Z euler) | helps Nephilim, hurts Aracoix |
| per-frame translation or scale | the clip's `pos` is identically zero and `scale` exactly 1 |
| quaternion component order alone, no joint frame | 4 orders scored, best 15.31; the two must change together |

An exhaustive 192-variant sweep (24 component permutations x 8 sign patterns, joint frame
on) does contain variants that score the two anchored angles better than scalar-first.
They are overfitting -- three degrees of freedom against two numbers -- and the best of
them have aggregates of 53. Scalar-first is what `Math.dll` says the bytes are (section 3),
and it is the one that needs no per-bone exception.

**Consequence for anything walking the hierarchy itself.** `tools/export_motions.py` ran
its own forward-kinematics loop and needed the same conjugation; it now carries `axis` in
`skeletons.json` and applies it. `AssetManager._fold_wings` authors rotations that are fed
back through `pose()`, so it authors through `ArcBoneRecord.clip_rotation` to land in the
frame `pose` will read them in. Any new consumer has the same obligation.

**Left open.** `_fold_wings` still overrides rigs 18/20/70/117 with a synthetic fold, and
for rig 18 the clip now supplies a real one. It is no longer obviously needed there. That
only affects the `stand_pose` / `wing_fold_pose` export path, not the clip renders.

## 7) Reproducing this

```bash
# strings
python -c "import re;from pathlib import Path;\
b=Path(r'C:/code/lakebane/sb.exe').read_bytes();\
print('\n'.join(sorted(set(x.decode('latin-1') for x in re.findall(rb'[ -~]{6,}',b) if b'ArcanePrime' in x))))"
```

Disassembly -- capstone is in `viewer_env`, the system Python does not have it. The
joint-frame setup of section 4:

```bash
./viewer_env/Scripts/python.exe tools/disasm_sb.py 0x5d78c0 120   # root, seeds identity
./viewer_env/Scripts/python.exe tools/disasm_sb.py 0x5d7ba0 100   # recursive body
```

To go from a Math.dll symbol to its call sites: `tools/pe_reader.py` parses the import
directory, and searching `.text` for `ff 15 <little-endian IAT address>` finds the callers.
The two cited above are `0x1ab0764` `MakeTripleRotate` and `0x1ab077c` `Quaternion::Inverse`.

Scoring a pose change:

```bash
./viewer_env/Scripts/python.exe tools/pose_invariants.py       # correctness, anchored on rig 18
./viewer_env/Scripts/python.exe tools/pose_baseline.py         # movement against the frozen pose
./viewer_env/Scripts/python.exe tools/pose_sheet.py --probe --tag <name>    # and look at it
./viewer_env/Scripts/python.exe tools/pose_render.py --ids 2002 --pose 18000010:0 --views side
```

That last one is the Aracoix idle at the frame the client video was compared against, and
is the single picture showing both the lean and the wing fold.
