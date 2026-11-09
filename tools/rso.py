"""Prepare the hbm_part.rso module for static recompilation.

Despite its name the module holds more than the HOME menu: the game calls into it
for its movies as well, so it runs often. The game links it at boot with OSLink, so its
relocated code sits at a fixed address (MEM1 0x8083d5f0 in the USA/Japan build).
Given a memory dump taken after linking, this finds the module, runs the normal
function analysis over its text and writes:

  out/rso_image.bin       relocated text section
  out/rso_info.json       {"text": addr, "size": n, "hash": fnv1a64, "data": [[addr, size], ...]}
  out/rso_functions.json  function list (same format as functions.json)

  python tools/rso.py [dump] [--out dir]

--out: where the three files go (default out/; out/eu/ for the European build, with
its dump out/eu/mem1_dump.bin, which tools/build_generated.py passes).

The dump is out/mem1_dump.bin (or out/mem2_dump.bin), which SRR_DUMPMEM=1 writes
(both) on the first call into code outside main.dol, or a MEM1/MEM2 dump from the TAS
`dump` command (out/dumps/<name>.mem1 / .mem2).
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dol import Section          # noqa: E402
from analyze import Analyzer, cross_targets, data_code_pointers   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RSO = os.path.join(ROOT, 'game', 'extracted', 'DATA', 'files', 'hbm_part.rso')
DUMPS = [(os.path.join(ROOT, 'out', 'mem1_dump.bin'), 0x80000000),
         (os.path.join(ROOT, 'out', 'mem2_dump.bin'), 0x90000000)]
OUT = os.path.join(ROOT, 'out')


def fnv1a64(b):
    h = 0xCBF29CE484222325
    for x in b:
        h = ((h ^ x) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


class Image:
    """Minimal Dol-like view (what Analyzer needs) over the linked module."""

    def __init__(self, text, data):
        self.sections = [text] + data
        self.text = [text]
        self.data = data
        self.entry = text.addr

    def section_at(self, addr):
        for s in self.sections:
            if s.addr <= addr < s.end:
                return s
        return None

    def is_text(self, addr):
        s = self.section_at(addr)
        return s is not None and s.kind == 'text'

    def read32(self, addr):
        s = self.section_at(addr)
        if s is None:
            return None
        return struct.unpack_from('>I', s.data, addr - s.addr)[0]

    def words(self, sec):
        n = sec.size // 4
        return struct.unpack(f'>{n}I', sec.data[:n * 4])


def main():
    global OUT
    if '--out' in sys.argv:
        i = sys.argv.index('--out')
        OUT = sys.argv[i + 1]
        del sys.argv[i:i + 2]
    rso = open(RSO, 'rb').read()
    if len(sys.argv) > 1:
        dumps = [(sys.argv[1], 0x90000000 if sys.argv[1].endswith('mem2') else 0x80000000)]
    else:
        dumps = [d for d in DUMPS if os.path.exists(d[0])]
        if not dumps:
            sys.exit('no memory dump: run the game with SRR_DUMPMEM=1 (see the module docstring)')
    nsec, secoff = struct.unpack_from('>II', rso, 8)
    secs = [struct.unpack_from('>II', rso, secoff + 8 * i) for i in range(nsec)]
    text_off, text_size = secs[1]
    # locate the linked module: relocations only touch some words, so find candidates
    # from 32-byte runs of the text, then keep the one where most words match (a run
    # can also match repeated code elsewhere)
    code = rso[text_off:text_off + text_size]
    best = (0, None)
    for path, base in dumps:
        mem = open(path, 'rb').read()
        for off in range(0x800, text_size - 0x20, 0x4000):
            i = mem.find(code[off:off + 0x20])
            if i < 0 or i < off:
                continue
            cand = mem[i - off:i - off + text_size]
            score = sum(cand[k:k + 4] == code[k:k + 4] for k in range(0, text_size, 4))
            if score > best[0]:
                best = (score, (path, base, base + i - off))
    if best[0] < text_size // 8:
        sys.exit('module text not found in the dump')
    path, DUMP_BASE, text_addr = best[1]
    mem = open(path, 'rb').read()
    load_base = text_addr - text_off
    print(f'module loaded at {load_base:08x}, text {text_addr:08x}+{text_size:x}')
    img = mem[text_addr - DUMP_BASE:text_addr - DUMP_BASE + text_size]
    text = Section('text', 1, 0, text_addr, img)
    data = []
    for idx, (off, size) in enumerate(secs[2:], start=2):
        if off and size and load_base + off + size - DUMP_BASE <= len(mem):
            a = load_base + off
            data.append(Section('data', idx, 0, a, mem[a - DUMP_BASE:a - DUMP_BASE + size]))

    view = Image(text, data)
    an = Analyzer(view, [text_addr])
    funcs = an.run()
    jt = {t for f in funcs for ts in f.jumptables.values() for t in ts}
    an.starts |= data_code_pointers(an, jt) - an.starts
    while True:
        funcs = an.run()
        extra = cross_targets(an, funcs) - an.starts
        if not extra:
            break
        an.starts |= extra
    funcs = [f for f in funcs if text_addr <= f.start < text_addr + text_size]
    print(f'{len(funcs)} functions')
    open(os.path.join(OUT, 'rso_image.bin'), 'wb').write(img)
    json.dump({'text': text_addr, 'size': text_size, 'hash': fnv1a64(img),
               'data': [[s.addr, s.size] for s in data]},
              open(os.path.join(OUT, 'rso_info.json'), 'w'))
    json.dump([f.to_json() for f in funcs], open(os.path.join(OUT, 'rso_functions.json'), 'w'))


if __name__ == '__main__':
    main()
