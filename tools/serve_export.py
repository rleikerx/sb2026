#!/usr/bin/env python3
"""
Serve the export folder so the browser-based viewer can read it.

`python -m http.server` wedges here: the viewer holds keep-alive connections
open while streaming multi-megabyte GLBs, and a request that arrives behind one
of those never gets answered. This uses a threading server with keep-alive
disabled per response, which is what makes a browse session usable.

Usage:
    python tools/serve_export.py                 # serves export_aegisfall on :8777
    python tools/serve_export.py --port 9000 --root export_aegisfall
"""

from __future__ import annotations

import argparse
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".glb": "model/gltf-binary",
        ".gltf": "model/gltf+json",
        ".js": "text/javascript",
        ".json": "application/json",
    }

    protocol_version = "HTTP/1.1"

    def end_headers(self):
        # Reference browsing means reloading edited files constantly.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        # Unbuffered, so progress is visible when run in the background.
        sys.stdout.write(f"{self.address_string()} {fmt % args}\n")
        sys.stdout.flush()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(REPO_ROOT / "export_aegisfall"))
    ap.add_argument("--port", type=int, default=8777)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"root not found|path={root}", file=sys.stderr)
        return 2

    handler = partial(Handler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    server.daemon_threads = True

    print(f"serving {root}")
    print(f"open http://localhost:{args.port}/viewer/")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
