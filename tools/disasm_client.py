"""Disassemble named exports out of the client's Math.dll (PE32 x86).

The client ships an unstripped `Math.dll` with 222 named exports, which is where the
engine's quaternion and Euler conventions can be read rather than guessed. See
docs/CLIENT_BINARY_FINDINGS.md for what came out of it.

Needs capstone, which lives in viewer_env rather than the system Python:

    ./viewer_env/Scripts/python.exe tools/disasm_client.py         "?MakeTripleRotate@Quaternion@math@@SA?AV12@ABVVector3@2@@Z"

Pass --list to dump every exported symbol with its RVA.
"""
import os, struct, sys
from pathlib import Path
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

DLL = Path(os.environ.get("SB_CLIENT_MATH_DLL", r"C:/code/lakebane/Math.dll"))
d = DLL.read_bytes()
pe = struct.unpack_from("<I", d, 0x3C)[0]
nsec = struct.unpack_from("<H", d, pe+6)[0]
optsz = struct.unpack_from("<H", d, pe+20)[0]
magic = struct.unpack_from("<H", d, pe+24)[0]
imagebase = struct.unpack_from("<I", d, pe+24+28)[0]
dd = pe+24+(96 if magic == 0x10b else 112)
erva, esz = struct.unpack_from("<II", d, dd)
secs = []
for i in range(nsec):
    off = pe+24+optsz+i*40
    vsz, va, rsz, praw = struct.unpack_from("<IIII", d, off+8)
    secs.append((va, vsz, praw, rsz))

def r2o(rva):
    for va, vsz, praw, rsz in secs:
        if va <= rva < va+max(vsz, rsz):
            return praw+(rva-va)
    return None

eo = r2o(erva)
nfun, nnam = struct.unpack_from("<II", d, eo+20)
afun, anam, aord = struct.unpack_from("<III", d, eo+28)
fo, no, oo = r2o(afun), r2o(anam), r2o(aord)
exports = {}
for i in range(nnam):
    nr = struct.unpack_from("<I", d, no+i*4)[0]
    o = r2o(nr); e = d.index(b"\x00", o)
    name = d[o:e].decode("latin-1")
    ordi = struct.unpack_from("<H", d, oo+i*2)[0]
    frva = struct.unpack_from("<I", d, fo+ordi*4)[0]
    exports[name] = frva

md = Cs(CS_ARCH_X86, CS_MODE_32)
md.detail = False

def show(sym, limit=90):
    rva = exports.get(sym)
    if rva is None:
        print("!! not exported:", sym); return
    off = r2o(rva)
    code = d[off:off+700]
    print("\n=== %s   rva=%08x ===" % (sym, rva))
    n = 0
    for ins in md.disasm(code, imagebase+rva):
        print("  %-8s %s" % (ins.mnemonic, ins.op_str))
        n += 1
        if ins.mnemonic == "ret" or n >= limit:
            break

if "--list" in sys.argv[1:]:
    for name, rva in sorted(exports.items(), key=lambda kv: kv[1]):
        print("%08x  %s" % (imagebase+rva, name))
else:
    for s in sys.argv[1:]:
        show(s)
