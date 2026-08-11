"""Minimal PE32 reader: section map, RVA<->file offset, and absolute-VA xref search.

Shared by tools/disasm_client.py and tools/disasm_sb.py. See
docs/CLIENT_BINARY_FINDINGS.md for what has been read out of the client with it.
"""
import struct
from pathlib import Path
class PE:
    def __init__(self, path):
        self.d = Path(path).read_bytes()
        d = self.d
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        self.nsec = struct.unpack_from("<H", d, pe+6)[0]
        optsz = struct.unpack_from("<H", d, pe+20)[0]
        magic = struct.unpack_from("<H", d, pe+24)[0]
        self.base = struct.unpack_from("<I", d, pe+24+28)[0]
        self.secs = []
        for i in range(self.nsec):
            off = pe+24+optsz+i*40
            nm = d[off:off+8].rstrip(b"\x00").decode("latin-1", "replace")
            vsz, va, rsz, praw = struct.unpack_from("<IIII", d, off+8)
            self.secs.append((nm, va, vsz, praw, rsz))
    def o2va(self, off):
        for nm, va, vsz, praw, rsz in self.secs:
            if praw <= off < praw+rsz:
                return self.base+va+(off-praw)
        return None
    def va2o(self, va):
        r = va-self.base
        for nm, vaX, vsz, praw, rsz in self.secs:
            if vaX <= r < vaX+max(vsz, rsz):
                o = praw+(r-vaX)
                return o if o < len(self.d) else None
        return None
    def xrefs(self, va, limit=40):
        """file offsets where the 4-byte little-endian VA appears (absolute operand)."""
        needle = struct.pack("<I", va)
        out, i = [], 0
        while len(out) < limit:
            i = self.d.find(needle, i)
            if i < 0: break
            out.append(i); i += 1
        return out
