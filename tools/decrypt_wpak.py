#!/usr/bin/env python3
"""
Decrypt the client's `.wpak` config archives.

Every `.cfg` inside a `.wpak` is Blowfish-CFB with one fixed key and IV, which is why 140 files all
decrypt in their first block from a single derived keystream and diverge after it.

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wpak", action="append", help="a .wpak to decrypt (repeatable)")
    ap.add_argument("--all", action="store_true", help="every .wpak under the client")
    ap.add_argument("--client", default=str(DEFAULT_CLIENT))
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "config"))
    args = ap.parse_args()

    packs = [Path(p) for p in (args.wpak or [])]
    if args.all or not packs:
        packs = sorted(Path(args.client).rglob("*.wpak"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

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
            if not name.lower().endswith(".cfg"):
                # The map packs carry plain TGAs beside their one .cfg; pass them through.
                (target / Path(name).name).write_bytes(raw)
                skipped += 1
                continue
            plain = decrypt(raw)
            score = readable(plain)
            (target / Path(name).name).write_bytes(plain)
            if score >= 85:
                good += 1
            else:
                bad += 1
                print(f"    {name}: only {score}% printable after decrypt")
        total += good
        failed += bad
        print(f"  {pack.name:<28} {good} decrypted, {bad} suspect, {skipped} passed through")

    print(f"\ncfg files decrypted {total}, suspect {failed}")
    print(f"wpak|elapsed={time.time() - started:.1f}s|out={out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
