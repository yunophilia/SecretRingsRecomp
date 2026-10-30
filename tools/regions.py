"""The game's releases and the main.dol builds they use.

USA (RSRE8P) and Japan (RSRJ8P) ship the same main.dol; Europe (RSRP8P) has its own
build. The runtime's overrides and patches are written against the USA/Japan addresses
(the base code set); the European code set is recompiled with an eu_ prefix and its
overridden functions are found by matching its functions to the base build's.
"""
import bisect
import difflib
import hashlib

# main.dol SHA-1 -> (code set, releases)
CODE_SETS = {
    'c4d611da44cf89a6bc76c2ec86c2449ee29abcdb': ('base', ('RSRE8P', 'RSRJ8P')),
    '9ffb9cf282f6ff416f995104021b451df91ce522': ('eu', ('RSRP8P',)),
}


def dol_sha1(path):
    with open(path, 'rb') as fp:
        return hashlib.sha1(fp.read()).hexdigest()


def _norm(w):
    """An instruction without what moves when code or data shifts: branch displacements
    and 16-bit immediates/offsets (address halves, small-data offsets)."""
    op = w >> 26
    if op in (16, 18):            # bc, b
        return (op << 26) | (w & 3)
    if op in (12, 13, 14, 15, 24, 25) or 32 <= op <= 55:   # addic, addi/addis, ori/oris, loads/stores
        return w & 0xFFFF0000
    return w


def _shape(dol, f):
    return hashlib.sha1(b''.join(_norm(dol.read32(a)).to_bytes(4, 'big')
                                 for a in range(f['start'], f['end'], 4))).digest()


def match_functions(dol_a, funcs_a, dol_b, funcs_b):
    """{start in a: start in b} for functions with the same code apart from relocated
    addresses, aligned in address order (both builds come from the same sources)."""
    fa = [f for f in funcs_a if dol_a.is_text(f['start'])]
    fb = [f for f in funcs_b if dol_b.is_text(f['start'])]
    sa = [_shape(dol_a, f) for f in fa]
    sb = [_shape(dol_b, f) for f in fb]
    out = {}
    sm = difflib.SequenceMatcher(None, sa, sb, autojunk=False)
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            out[fa[i + k]['start']] = fb[j + k]['start']
    return out


class AddrMap:
    """Maps addresses inside matched functions of one build to the other."""

    def __init__(self, funcs_a, matches):
        self.ends = {f['start']: f['end'] for f in funcs_a}
        self.starts = sorted(matches)
        self.matches = matches

    def __call__(self, addr):
        i = bisect.bisect_right(self.starts, addr) - 1
        if i < 0:
            return None
        s = self.starts[i]
        if addr >= self.ends.get(s, s):
            return None
        return self.matches[s] + (addr - s)
