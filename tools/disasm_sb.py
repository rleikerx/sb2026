"""Disassemble sb.exe at a virtual address, annotating .data string operands.

    ./viewer_env/Scripts/python.exe tools/disasm_sb.py 0x5d64b0 55

capstone lives in viewer_env, not the system Python. Useful anchors are listed in
docs/CLIENT_BINARY_FINDINGS.md -- the ASF token table starts at 0x5d5e6d.
"""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pe_reader import PE
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
p = PE(os.environ.get("SB_CLIENT_EXE", r"C:/code/lakebane/sb.exe"))
md = Cs(CS_ARCH_X86, CS_MODE_32)
start = int(sys.argv[1], 16)
count = int(sys.argv[2]) if len(sys.argv) > 2 else 60
off = p.va2o(start)
code = p.d[off:off+count*8]
for ins in md.disasm(code, start):
    tgt = ""
    for tok in ins.op_str.replace(",", " ").split():
        if tok.startswith("0x"):
            try:
                v = int(tok, 16)
            except ValueError:
                continue
            o = p.va2o(v)
            if o and 0x012c1000 <= o < 0x01373000:
                s = p.d[o:o+40].split(b"\x00")[0]
                if 2 < len(s) < 40 and all(32 <= c < 127 for c in s):
                    tgt = '   ; "%s"' % s.decode("latin-1")
    print("%08x  %-7s %s%s" % (ins.address, ins.mnemonic, ins.op_str, tgt))
    count -= 1
    if count <= 0:
        break
