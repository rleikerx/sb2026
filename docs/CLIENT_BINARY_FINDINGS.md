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

## 4) What this says about `ArcSkeleton.pose()`

`pose()` composes `parent * clip_quat` and never uses `bone.axis`. 39 of skeleton 18's
55 bones carry a non-zero axis, so under a literal reading of ASF that looks wrong.

**The evidence says it is nevertheless correct**, i.e. the caches are pre-baked and
`axis` survives as source metadata:

- Applying the axis as `C * M * C^-1` moves every rig by 0.08–0.44 stature units and
  visibly **breaks** the humanoids — arms splay outward instead of hanging. The
  current math renders them correctly.
- No objective invariant separates the two. Foot skate (a planted foot should not
  slide while the root advances) scores 0.0130–0.0138 across every candidate, because
  every leg bone carries the benign 90-degree X axis and the leg chain is near-invariant
  under the conjugation.

Do not "fix" this without a test that can tell the two apart. The one that would:
a frame-accurate comparison against the client for a rig whose axis is *not* a right-angle
multiple. Skeleton 18 has 6 such bones; the wing roots carry +/-167.3 degrees on Z.

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

What this does **not** answer: what reads `bone+0x30` during pose evaluation. That is the
question the wing fold turns on, and it is not in the ASF parser. Note also that the ASF
and AMC text loaders are likely dev-only paths -- the shipped client reads
`Skeleton.cache` and `Motion.cache`, so the runtime composition lives in the cache-load
and pose-evaluation code, not here. `<ArcMotion::LoadAMC>` is referenced from `0x5ba087`
and `0x5baca1` if that path is wanted.

Tooling: `tools/pe_reader.py` (section map, VA<->offset, xref search) and
`tools/disasm_sb.py` (disassemble at a VA, annotating `.data` string operands).

## 6) Open: the Aracoix wing fold

Unresolved. The client's idle folds the Aracoix wings down the back to ankle height;
our render of the same authored clip (`18000010`, slot 10) holds them out horizontally.
Ruled out with evidence, so nobody repeats them:

| hypothesis | verdict |
|---|---|
| hidden bind matrix in the 36 skipped bytes per bone | zero on all 55 bones |
| wrong frame chosen | idle clip is static across all 238 frames |
| Euler order | XYZ/YXZ/XZY identical here; ZYX clearly wrong; client uses ZYX-composed = `Rz@Ry@Rx` |
| `direction` also in the joint frame | collapses the model entirely |
| handedness (negated Z euler) | helps Nephilim, hurts Aracoix |
| axis composition `C*M*C^-1` | see section 4; 40 variants scored, best 12.84 deg vs 16.11 current |
| quaternion component order | 4 orders scored, best 15.31 deg; no remap at all gives 166 deg, so a remap is definitely required |

A systematic defect found late and still unexplained: **every animation leans back**.
Client video of the Aracoix idle shows the spine vertical; our render of the same clip
and frame leans **13.5 degrees back**, and the mean across rigs is 8-14 degrees while the
rest pose is 0.0. It is not the root bone (root pitch is 0.3 to -3.3 on humanoid rigs);
the lean is carried by LOWERBACK (-5.4 mean pitch) and UPPERBACK (-11.35). `tools/pose_invariants.py`
scores it.

One concrete smaller finding on the way: `ArcMotion`'s quaternion remap exempts bone 0
(`if y == 0`) from the y/z swap it applies to every other bone. Dropping that exemption
scores better -- 15.31 against 16.11 -- and a per-bone special case is the signature of
trial-and-error rather than derivation. It is not the defect, but it looks wrong.

Also established from client video: **the Nephilim idle spreads its wings and never
folds them.** `_fold_wings` is aimed wrong for rigs 115/116.

## 7) Reproducing this

```bash
# exports, with RVAs
python tools/... # or inline: parse the PE export directory of Math.dll

# disassembly (capstone is in viewer_env)
./viewer_env/Scripts/python.exe scratch/disasm.py \
    "?MakeTripleRotate@Quaternion@math@@SA?AV12@ABVVector3@2@@Z"

# strings
python -c "import re;from pathlib import Path;\
b=Path(r'C:/code/lakebane/sb.exe').read_bytes();\
print('\n'.join(sorted(set(x.decode('latin-1') for x in re.findall(rb'[ -~]{6,}',b) if b'ArcanePrime' in x))))"
```

`viewer_env` has `capstone` 5.0.7; the system Python does not.
