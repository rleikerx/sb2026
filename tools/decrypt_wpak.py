#!/usr/bin/env python3
"""
Decrypt the client's `.wpak` config archives.

Every member of a `.wpak` is Blowfish-CFB with one fixed key and IV — not only the `.cfg` files —
which is why they all decrypt in their first block from a single derived keystream and diverge after
it. The uncompressed TGAs in the map packs are the one exception and ship in the clear.

    c[i] = p[i] XOR E(c[i-1]),  c[-1] = IV

The key is **not** a literal anywhere in the binaries — 419 million byte-window candidates found
nothing, because `sb.exe` builds it a byte at a time on the stack:

    0x0054dee2  mov byte ptr [ebp-0x20], 0x85
    0x0054dee6  mov byte ptr [ebp-0x1f], 0x71
    ...                                          16 stores
    0x0054df39  push 0x10                        ; key length
    0x0054df3b  push ecx                         ; lea ecx, [ebp-0x20]
    0x0054df3e  call ArcBlowfishEncryption::ctor

Found by disassembling from the Blowfish P-array constant (0x243F6A88) to its one reference, to the
key-schedule routine, to its single caller through an incremental-link thunk. The key-schedule also
clamps key length to 0x48 = 72 rather than the usual 56, which is worth knowing before assuming a
library will accept whatever this client uses elsewhere.

Usage:
    python tools/decrypt_wpak.py --wpak "<client>/Config/Config.wpak" --out export_aegisfall/config
    python tools/decrypt_wpak.py --all --out export_aegisfall/config
"""

from __future__ import annotations

import argparse
import sys
import time
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Crypto.Cipher import Blowfish

KEY = bytes([0x85, 0x71, 0x40, 0x3C, 0x14, 0x50, 0x0B, 0x52,
             0x73, 0x2D, 0x10, 0x08, 0x63, 0x59, 0x5B, 0xAA])
#: E(IV) for block 0, recovered from known plaintext; the IV itself is D() of this.
FIRST = bytes.fromhex("6b3bcb49a0c07111")
DEFAULT_CLIENT = Path(r"C:\Code\Shadowbane - Throne of Oblivion")

#: What each pack yields. Recorded here rather than in the caller so there is one copy, and
#: checked by `--verify` alongside the plaintext assertion. The count is the weaker half of
#: that check: through every run before this one the files were all present, all the right
#: size, and all still ciphertext, because only `*.cfg` was being decrypted.
EXPECTED = {
    "Config": 143, "Environment": 35, "Transitions": 40, "VendorENGLISH": 6,
    "AerynthIcons": 49, "DalgothIcons": 49, "VorringiaIcons": 49,
    "GeneralItemTables": 64, "ItemTables": 217, "ModTables": 158, "ModTypeTables": 264,
}


def iv() -> bytes:
    return Blowfish.new(KEY, Blowfish.MODE_ECB).decrypt(FIRST)


def decrypt(blob: bytes) -> bytes:
    """CFB with an 8-byte block, feeding back ciphertext. The tail is a short final block."""
    cipher = Blowfish.new(KEY, Blowfish.MODE_ECB)
    out = bytearray()
    feedback = iv()
    for i in range(0, len(blob), 8):
        chunk = blob[i:i + 8]
        stream = cipher.encrypt(feedback)
        out += bytes(a ^ b for a, b in zip(chunk, stream))
        feedback = chunk if len(chunk) == 8 else chunk + stream[len(chunk):]
    return bytes(out)


def readable(data: bytes) -> int:
    if not data:
        return 0
    ok = sum(1 for b in data if 32 <= b < 127 or b in (9, 10, 13))
    return 100 * ok // len(data)


def text_score(data: bytes) -> int:
    """`readable`, but through the BOM. The vendor dialogs and the zone data are UTF-16, where every
    other byte is a NUL — they score about 49 raw, and would read as a failed decrypt."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return readable(data.decode("utf-16", errors="ignore").encode("latin-1", errors="replace"))
    return readable(data)


def verify(out: Path) -> int:
    """Check the decrypted config bundle on disk: every directory present and the right size, and
    every file actually plaintext. Decrypting is cheap and the client is not always mounted, so
    this runs standalone -- it reads only what has already been written."""
    problems: list[str] = []
    files = ciphertext = 0
    for name in sorted(EXPECTED):
        folder = out / name
        if not folder.is_dir():
            problems.append(f"{name}: missing")
            print(f"  {name:<20} MISSING")
            continue
        members = sorted(p for p in folder.iterdir() if p.is_file())
        want = EXPECTED[name]
        bad = []
        for member in members:
            raw = member.read_bytes()
            if member.suffix.lower() == ".tga":
                # The one kind that ships in the clear; a TGA that decrypts to text would mean
                # the pack changed, not that the check is wrong.
                if raw[:3] != b"\x00\x00\x02":
                    bad.append(member.name)
                continue
            files += 1
            if text_score(raw) < 85:
                bad.append(member.name)
        ciphertext += len(bad)
        note = ""
        if len(members) != want:
            problems.append(f"{name}: {len(members)} files, expected {want}")
            note = f"  expected {want}"
        if bad:
            problems.append(f"{name}: {len(bad)} not plaintext ({', '.join(bad[:3])} ...)")
            note += f"  {len(bad)} NOT PLAINTEXT"
        print(f"  {name:<20} {len(members):>4} files{note}")

    print(f"\nverify|dirs={len(EXPECTED)}|files={files}|ciphertext={ciphertext}"
          f"|problems={len(problems)}")
    for problem in problems:
        print(f"  {problem}")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wpak", action="append", help="a .wpak to decrypt (repeatable)")
    ap.add_argument("--all", action="store_true", help="every .wpak under the client")
    ap.add_argument("--verify", action="store_true",
                    help="check the bundle already on disk is complete and plaintext; decrypt nothing")
    ap.add_argument("--client", default=str(DEFAULT_CLIENT))
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "config"))
    args = ap.parse_args()

    if args.verify:
        return verify(Path(args.out))

    packs = [Path(p) for p in (args.wpak or [])]
    if args.all or not packs:
        packs = sorted(Path(args.client).rglob("*.wpak"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if not packs:
        # Not a failure: the client is not always mounted, and the bundle already on disk is
        # what the exporters read. `--verify` is the check that it is intact.
        print(f"no .wpak under {args.client} - nothing to decrypt; run --verify to check {out}")
        return 0

    print(f"key {KEY.hex(' ')}")
    print(f"iv  {iv().hex(' ')}\n")
    started = time.time()
    total = failed = 0

    for pack in packs:
        try:
            archive = zipfile.ZipFile(pack)
        except Exception as error:
            print(f"  {pack.name}: not a zip ({error})")
            continue
        target = out / pack.stem
        target.mkdir(parents=True, exist_ok=True)
        good = bad = skipped = 0
        for name in archive.namelist():
            raw = archive.read(name)
            # Decrypt every member and let the plaintext decide. An earlier version skipped
            # anything not named `*.cfg`, on the grounds that the map packs carry plain TGAs —
            # true of the TGAs and of nothing else, so the 703 treasure tables, the six vendor
            # dialogs and 18 assorted text files were written back out still encrypted. The TGAs
            # are the only members that fail this check, and the pass-through tally says so.
            plain = decrypt(raw)
            score = text_score(plain)
            if score >= 85:
                (target / Path(name).name).write_bytes(plain)
                good += 1
                continue
            if name.lower().endswith(".tga") and raw[:3] == b"\x00\x00\x02":
                (target / Path(name).name).write_bytes(raw)
                skipped += 1
                continue
            (target / Path(name).name).write_bytes(plain)
            bad += 1
            print(f"    {name}: only {score}% printable after decrypt")
        total += good
        failed += bad
        print(f"  {pack.name:<28} {good} decrypted, {bad} suspect, {skipped} passed through")

    print(f"\nfiles decrypted {total}, suspect {failed}")
    print(f"wpak|elapsed={time.time() - started:.1f}s|out={out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
