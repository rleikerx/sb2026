"""
Cache Archive - Random-access reader for Shadowbane `*.cache` containers.

Container layout (little-endian), same as `arcane.util.ArcFileCache`:

    header  u32 num_resources | u32 data_start | u32 data_end | u32 0xffffffff
    index   num_resources x { u64 resource_id (stored as two byte-swapped dwords)
                              u32 offset | u32 decompressed_len | u32 compressed_len }
    body    record bytes at `offset`, zlib-deflated when decompressed_len > compressed_len

`ArcFileCache.load_cache_file` decompresses every record up front, which is not
usable for the viewer: `Textures.cache` alone is 467 MB compressed. This keeps
only the index resident (20 bytes per entry) and seeks per record on demand.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from arcane.util import ResStream

_HEADER = struct.Struct("<IIII")
_INDEX_ENTRY = struct.Struct("<IIIII")  # id_hi, id_lo, offset, decompressed_len, compressed_len


class CacheArchive:
    """
    Lazily-read `.cache` archive.

    Records are addressed by the 64-bit resource ID used throughout the asset
    graph (mesh IDs, render IDs, cobject IDs, ...).
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        # resource_id -> (offset, decompressed_len, compressed_len)
        self._index: Dict[int, Tuple[int, int, int]] = {}
        self.duplicate_count = 0
        self._handle = None

        self._read_index()

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------
    def _read_index(self) -> None:
        with self.path.open("rb") as f:
            header = f.read(_HEADER.size)
            if len(header) < _HEADER.size:
                raise ValueError(f"cache truncated|path={self.path}")
            num_resources, _data_start, _data_end, _magic = _HEADER.unpack(header)

            table = f.read(num_resources * _INDEX_ENTRY.size)
            if len(table) < num_resources * _INDEX_ENTRY.size:
                raise ValueError(
                    f"cache index truncated|path={self.path}|expected={num_resources}"
                )

        for id_hi, id_lo, offset, dec_len, comp_len in _INDEX_ENTRY.iter_unpack(table):
            # The 64-bit ID is stored as two dwords in swapped order: the first
            # dword on disk is the high half (see `ArcFileCache.read_qword`).
            resource_id = (id_hi << 32) | id_lo
            if resource_id in self._index:
                self.duplicate_count += 1
            # Later entries shadow earlier ones, matching the overwrite order a
            # sequential extraction of the archive would produce.
            self._index[resource_id] = (offset, dec_len, comp_len)

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------
    def ids(self) -> List[int]:
        return sorted(self._index)

    def __contains__(self, resource_id: int) -> bool:
        return resource_id in self._index

    def __len__(self) -> int:
        return len(self._index)

    def read(self, resource_id: int) -> Optional[bytes]:
        """Return the decompressed record body, or None if the ID is absent."""
        entry = self._index.get(resource_id)
        if entry is None:
            return None

        offset, dec_len, comp_len = entry
        if self._handle is None or self._handle.closed:
            self._handle = self.path.open("rb")

        self._handle.seek(offset)
        data = self._handle.read(comp_len)
        if dec_len > comp_len:
            data = zlib.decompress(data)
        return data

    def stream(self, resource_id: int) -> Optional[ResStream]:
        """Return the record wrapped in a `ResStream` ready for `load_binary`."""
        data = self.read(resource_id)
        return None if data is None else ResStream(data)

    def close(self) -> None:
        if self._handle is not None and not self._handle.closed:
            self._handle.close()
        self._handle = None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"CacheArchive(path={self.path.name!r}, records={len(self._index)})"
