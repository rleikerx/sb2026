#!/usr/bin/env python3
"""
Fetch the power cameo images from the Morloch wiki.

**This is the one bundle that does not come out of the client**, and that is a finding rather than
an oversight. The cameos were searched for exhaustively in the install — 4,730 unclaimed square
textures scored for circular content, both skin archives, all eleven `.wpak` files, the UTF-16
string tables, and every DLL and EXE grepped for `cameo`/`cam.tga` — and they are not there. The
client references them; it does not ship them. See the *Not provided* note in the export README.

What the client *does* have is the mapping, and Aegisfall already imported it: 460 powers each name
a cameo, drawn from a shared set of 195, so `Heal cam.png` serves twelve healing spells. This tool
supplies the bytes behind those names.

The wiki serves them through MediaWiki's `Special:FilePath`, which redirects to the real file:

    https://morloch.shadowbaneemulator.com/index.php/Special:FilePath/Alac_cam.png

Requests are spaced deliberately — this is a small community wiki and 195 files is not a reason to
hammer it. A cached file is never refetched, so re-runs cost nothing.

Usage:
    python tools/fetch_cameos.py --names <file with one image name per line>
    python tools/fetch_cameos.py --names cameos.txt --size 64
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image

BASE = "https://morloch.shadowbaneemulator.com/index.php/Special:FilePath/"
MEDIA = "http://morloch.shadowbaneemulator.com/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def get(url: str, timeout: int) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            data = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None
    # A wiki with no such file answers with an HTML error page, not an image.
    return data if data[:8] == b"\x89PNG\r\n\x1a\n" or data[:2] == b"\xff\xd8" else None


def from_wayback(name: str, timeout: int) -> bytes | None:
    """
    The live wiki has lost some of these; the Wayback Machine has not.

    Six images the power table names — `Backstab.png`, `Buchinine.png`, `Galpa.png`,
    `Gorgons.png`, `Magusbane.png`, `Pellegorn.png` — 404 on the wiki today but are present in
    2014 snapshots of the class pages that reference them. They are also exactly the six that
    break the `X cam.png` naming convention, which is probably why they were the ones lost.

    Wayback never captured the `Special:FilePath` redirect — only the direct `/images/...` URLs the
    pages embed. MediaWiki derives that path from the MD5 of the *filename*: `Backstab.png` hashes
    to `7a7a…`, so it lives at `/images/7/7a/Backstab.png`. Verified against all six.

    `id_` asks Wayback for the original bytes rather than its rewritten page.

    Wayback throttles bursts hard — asking for six in a row got one through and refused the rest —
    so each attempt backs off rather than being reported as a miss the archive never made.
    """
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    path = f"images/{digest[0]}/{digest[:2]}/{urllib.parse.quote(name)}"
    for attempt in range(4):
        for stamp in ("2014id_", "id_"):
            data = get(f"https://web.archive.org/web/{stamp}/{MEDIA}{path}", timeout)
            if data is not None:
                return data
        time.sleep(3 * (attempt + 1))
    return None


def fetch(name: str, timeout: int) -> bytes | None:
    safe = name.replace(" ", "_")
    data = get(BASE + urllib.parse.quote(safe), timeout)
    if data is None:
        data = from_wayback(safe, timeout)
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--names", required=True, help="file listing one image name per line")
    ap.add_argument("--out", default=str(REPO_ROOT / "export_aegisfall" / "cameos"))
    ap.add_argument("--size", type=int, help="square-resize every image to N px (keeps the original too)")
    ap.add_argument("--resample", choices=("lanczos", "nearest"), default="lanczos",
                    help="lanczos preserves the anti-aliased rim; nearest stair-steps it")
    ap.add_argument("--delay", type=float, default=0.4, help="seconds between requests")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()

    names = [n.strip() for n in Path(args.names).read_text(encoding="utf-8").splitlines() if n.strip()]
    out = Path(args.out)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    if args.size:
        (out / f"{args.size}").mkdir(parents=True, exist_ok=True)

    print(f"{len(names)} distinct cameo images -> {out}")
    started = time.time()
    fetched = cached = failed = 0
    missing: list[str] = []
    index: list[dict] = []
    sizes: Counter = Counter()

    for i, name in enumerate(names, 1):
        target = raw / name.replace(" ", "_")
        if target.exists():
            cached += 1
            data = target.read_bytes()
        else:
            data = fetch(name, args.timeout)
            if data is None:
                failed += 1
                missing.append(name)
                print(f"  [{i:>3}/{len(names)}] MISSING {name}")
                time.sleep(args.delay)
                continue
            target.write_bytes(data)
            fetched += 1
            time.sleep(args.delay)

        try:
            with Image.open(target) as img:
                w, h = img.size
                sizes[f"{w}x{h}"] += 1
                row = {"name": name, "file": target.name, "w": w, "h": h}
                if args.size:
                    # **Lanczos, and nearest was tried and is wrong for this art.** The reasoning
                    # for nearest is sound in general — 28x28 sources, and 28 -> 56 is an exact 2x
                    # where each source pixel becomes a clean 2x2 block with no invented gradients,
                    # at two thirds the bytes. Rendered side by side it is plainly worse: a cameo
                    # is an *anti-aliased circle*, so nearest stair-steps the rim into a visible
                    # staircase while Lanczos carries the existing edge softening through. The
                    # apparent blur in the upscale is the source's own anti-aliasing, not damage.
                    filt = (Image.Resampling.NEAREST if args.resample == "nearest"
                            else Image.Resampling.LANCZOS)
                    square = img.convert("RGBA").resize((args.size, args.size), filt)
                    square.save(out / f"{args.size}" / target.name)
                    row["resized"] = f"{args.size}/{target.name}"
                    row["resample"] = args.resample
                index.append(row)
        except Exception as error:
            failed += 1
            missing.append(f"{name} (unreadable: {error})")

        if i % 25 == 0:
            print(f"  [{i:>3}/{len(names)}] fetched {fetched} cached {cached} failed {failed}",
                  flush=True)

    (out / "index.json").write_text(
        json.dumps({"generator": "tools/fetch_cameos.py",
                    "source": BASE,
                    "note": "power cameo art; the client references these names but ships no bytes",
                    "images": index}, indent=1), encoding="utf-8")

    print(f"\nfetched {fetched}  already cached {cached}  failed {failed}  of {len(names)}")
    print(f"source sizes: {dict(sizes.most_common(8))}")
    if missing:
        print(f"MISSING ({len(missing)}): {', '.join(missing[:20])}")
    print(f"cameos|elapsed={time.time() - started:.0f}s|out={out}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
