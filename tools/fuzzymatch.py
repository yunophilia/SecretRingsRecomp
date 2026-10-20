"""Find functions in this game's main.dol that correspond to functions of another DOL
(e.g. Sonic and the Black Knight), by comparing opcode sequences with immediates masked.

  python tools/fuzzymatch.py other.dol other_functions.json ADDR [ADDR...]
"""
import difflib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from dol import Dol

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def norm(w):
    op = w >> 26
    if op in (16, 18):            # branches: keep opcode + link bits
        return (op << 26) | (w & 3)
    if op in (14, 15, 24, 25, 26, 27, 28, 29, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 10, 11, 7, 8, 12, 13):
        return w & 0xFFE00000     # opcode + rD, drop rA/imm
    return w


def seq(dol, f):
    return [norm(dol.read32(a)) for a in range(f['start'], f['end'], 4)]


def main():
    odol = Dol(sys.argv[1])
    ofuncs = {f['start']: f for f in json.load(open(sys.argv[2]))}
    dol = Dol(os.path.join(ROOT, 'game', 'extracted', 'DATA', 'sys', 'main.dol'))
    funcs = json.load(open(os.path.join(ROOT, 'out', 'functions.json')))
    seqs = [(f, seq(dol, f)) for f in funcs]
    for a in sys.argv[3:]:
        a = int(a, 16)
        of = ofuncs[a]
        s = seq(odol, of)
        best = []
        for f, t in seqs:
            if not (0.5 * len(s) <= len(t) <= 2 * len(s) + 4):
                continue
            sm = difflib.SequenceMatcher(None, s, t, autojunk=False)
            if sm.real_quick_ratio() < 0.6 or sm.quick_ratio() < 0.6:
                continue
            r = sm.ratio()
            best.append((r, f['start'], f.get('name') or f.get('sig') or ''))
        best.sort(reverse=True)
        print(f'{a:08X} ({len(s)} ins, {of.get("name") or of.get("sig") or ""}):',
              '  '.join(f'{st:08X} {r:.2f} {n.split(chr(9))[0]}' for r, st, n in best[:3]))


if __name__ == '__main__':
    main()
