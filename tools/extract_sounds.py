#!/usr/bin/env python3
"""
Extract Sound.cache to WAV files.

Sound records are raw PCM behind a 16-byte header of four little-endian
int32s — payload length, sample rate, channel count, bits per sample — so the
export is a header rewrite, not a transcode. No audio dependencies needed;
Python's `wave` module writes the container.

Sound.cache is not part of the asset graph the viewer walks, so this reads the
archive directly rather than going through AssetManager.

Usage:
    python tools/extract_sounds.py --cache "C:/.../cache/Sound.cache" --out export_aegisfall/sounds
    python tools/extract_sounds.py --sample 10        # test run
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
import wave
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from assets.cache_archive import CacheArchive

HEADER = struct.Struct("<IIII")  # data_length, sample_rate, channels, bits_per_sample


def find_cache(explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    for candidate in (REPO_ROOT / "arcane_dump").rglob("Sound.cache"):
        return candidate
    return None


def write_wav(path: Path, pcm: bytes, rate: int, channels: int, bits: int) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(max(1, bits // 8))
        wav.setframerate(rate)
        wav.writeframes(pcm)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", help="path to Sound.cache (searched under arcane_dump/ if omitted)")
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "sounds"))
    ap.add_argument("--sample", type=int, help="only the first N records (test run)")
    ap.add_argument("--manifest", default="sounds.json")
    args = ap.parse_args()

    cache_path = find_cache(args.cache)
    if cache_path is None:
        print("Sound.cache not found. Pass --cache with its path.", file=sys.stderr)
        return 2

    archive = CacheArchive(cache_path)
    ids = archive.ids()
    if args.sample:
        ids = ids[: args.sample]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    records: List[dict] = []
    failed = odd = 0
    started = time.time()

    for sound_id in ids:
        data = archive.read(sound_id)
        if data is None or len(data) < HEADER.size:
            failed += 1
            continue

        length, rate, channels, bits = HEADER.unpack_from(data, 0)
        pcm = data[HEADER.size:]

        # The header length should describe the remainder exactly; trust the
        # smaller of the two rather than emitting a truncated or padded file.
        if length != len(pcm):
            odd += 1
            length = min(length, len(pcm))
        pcm = pcm[:length]

        if not pcm or channels not in (1, 2) or bits not in (8, 16, 24, 32) or not (1000 <= rate <= 192000):
            failed += 1
            print(f"skipped|id={sound_id}|rate={rate}|ch={channels}|bits={bits}|bytes={len(pcm)}",
                  file=sys.stderr)
            continue

        path = out_dir / f"{sound_id}.wav"
        try:
            write_wav(path, pcm, rate, channels, bits)
        except Exception as e:
            failed += 1
            print(f"write failed|id={sound_id}|err={e}", file=sys.stderr)
            continue

        frames = len(pcm) // max(1, (bits // 8) * channels)
        records.append({
            "sound_id": sound_id,
            "file": path.name,
            "sample_rate": rate,
            "channels": channels,
            "bits": bits,
            "frames": frames,
            "seconds": round(frames / rate, 3),
            "bytes": path.stat().st_size,
        })

    with (out_dir / args.manifest).open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    total_sec = sum(r["seconds"] for r in records)
    total_mb = sum(r["bytes"] for r in records) / 1024 / 1024
    print(f"sounds|written={len(records)}|failed={failed}|length_mismatch={odd}"
          f"|audio={total_sec / 60:.1f}min|size={total_mb:.1f}MB"
          f"|elapsed={time.time() - started:.1f}s|out={out_dir}")
    for r in records[:8]:
        print(f"  {r['sound_id']:>8}  {r['sample_rate']:>6} Hz  {r['channels']}ch  "
              f"{r['bits']}-bit  {r['seconds']:>7.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
