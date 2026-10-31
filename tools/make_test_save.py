"""Turns an adventure save into one with every world unlocked and every mission cleared,
for testing the later worlds (docs/tas.md, "Test saves").

  python tools/make_test_save.py <nand dir> [slot]

<nand dir> is a NAND folder (e.g. out/tasnand/<name>) whose save slot (default 0) is in
use: tools/tas/clear1.tas makes one from a fresh save. The file is changed in place.

game_N.sav (16 KiB, big-endian):
  0x00        checksum: minus the byte sum of everything after it
  0x09-0x0F   one byte per world after Lost Prologue: 1 = unlocked
  0x10-0x6FF  mission records, 16 bytes each: +0 unlocked (1; the first mission 2),
              +4 cleared, +14 best time. Rows of zeros between them are set the same
              way; the game accepts that.
"""
import os
import struct
import sys

nand = sys.argv[1]
slot = int(sys.argv[2]) if len(sys.argv) > 2 else 0
path = os.path.join(nand, 'title', '00010000', '52535245', 'data', f'game_{slot}.sav')
d = bytearray(open(path, 'rb').read())
if struct.unpack('>I', d[:4])[0] != (-sum(d[4:])) & 0xFFFFFFFF:
    sys.exit(f'{path}: bad checksum')
if not d[0x14]:
    sys.exit(f'{path}: the first mission is not cleared (an unused slot?); run tools/tas/clear1.tas first')
for w in range(0x09, 0x10):
    d[w] = 1
time = d[0x1E:0x20]
for o in range(0x20, 0x700, 16):
    d[o] = max(d[o], 1)
    d[o + 4] = 1
    d[o + 14:o + 16] = time
d[:4] = struct.pack('>I', (-sum(d[4:])) & 0xFFFFFFFF)
open(path, 'wb').write(d)
print(f'{path}: all worlds unlocked, all missions cleared')
