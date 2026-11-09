"""Static recompiler: PPC (Gekko/Broadway) DOL -> C++.

Every guest function becomes extern "C" void fn_XXXXXXXX(PPCContext& ctx, uint8_t* base)

unless the runtime overrides it (listed in out/overrides.txt), in which case the body is
emitted as fn_XXXXXXXX_impl so the runtime version can still call the original.

  recomp.py main.dol functions.json outdir [overrides.txt] [--eu main.dol functions.json outdir]

--eu: the European build of the game (tools/regions.py), recompiled together with the
base (USA/Japan) one. Its functions that match a base function share that function's
code and name: values that differ between the builds (data and return addresses,
callees) are written PPC_SEL(base, european), picked at run time. Matched functions
whose code cannot be shared that way, and the European build's own functions, are
emitted as eu_fn_XXXXXXXX into the European output directory, with that build's
dispatch table (PPCFuncMappings_eu) and source list (PPC_RECOMP_SOURCES_EU).
"""
import json
import os
import re
import sys

from dol import Dol
from ppc import decode

MMIO_SAFE_BASES = (1, 2, 13)   # r1 stack, r2/r13 small data: never MMIO

SPR_LR, SPR_CTR, SPR_XER = 8, 9, 1
GQR0 = 912


def h(v):
    return f'0x{v & 0xFFFFFFFF:X}'


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def mask32(mb, me):
    if mb <= me:
        m = ((0xFFFFFFFF >> mb) & (0xFFFFFFFF << (31 - me))) & 0xFFFFFFFF
    else:
        m = (((0xFFFFFFFF >> mb) | (0xFFFFFFFF << (31 - me))) & 0xFFFFFFFF)
    return m


class FuncGen:
    def __init__(self, rc, f):
        self.rc = rc
        self.dol = rc.dol
        self.f = f
        self.start = f['start']
        self.end = f['end']
        self.jt = {int(k): v for k, v in f.get('jt', {}).items()}
        self.out = []
        self.labels = set()
        self.calls = set()
        # added to this build's code addresses in labels and jump-table cases: the
        # European code is named by the USA build's addresses to share its code
        self.delta = 0

    def inside(self, t):
        return self.start <= t < self.end

    def emit(self, s):
        self.out.append('\t' + s)

    # ---------------------------------------------------------------- helpers
    def r(self, n):
        return f'ctx.r[{n}]'

    def ra0(self, n):
        return '0' if n == 0 else f'ctx.r[{n}]'

    def fr(self, n):
        return f'ctx.f[{n}].f64'

    def ps1(self, n):
        return f'ctx.f[{n}].ps1'

    def ld(self, size, ea_expr, base_reg, signed=False):
        safe = base_reg in MMIO_SAFE_BASES
        fn = {1: 'ld8', 2: 'ld16', 4: 'ld32'}[size]
        if safe:
            fn = fn + 'n'
        e = f'{fn}(base, {ea_expr})'
        if signed and size == 2:
            e = f'(uint32_t)(int32_t)(int16_t){e}'
        return e

    def st(self, size, ea_expr, val, base_reg):
        safe = base_reg in MMIO_SAFE_BASES
        fn = {1: 'st8', 2: 'st16', 4: 'st32'}[size]
        if safe:
            fn = fn + 'n'
        return f'{fn}(base, {ea_expr}, {val});'

    def cr_record(self, val):
        self.emit(f'PPC_CR0({val});')

    def call(self, target, ret_addr):
        self.calls.add(target)
        self.emit(f'ctx.lr = {h(ret_addr)}; {self.rc.sym(target)}(ctx, base);')

    def tailcall(self, target):
        if self.rc.is_func(target):
            self.calls.add(target)
            return f'{{ {self.rc.sym(target)}(ctx, base); return; }}'
        return f'{{ PPC_CALL_INDIRECT({h(target)}); return; }}'

    def cond(self, bo, bi):
        pre = ''
        parts = []
        if not (bo & 4):
            pre = '--ctx.ctr; '
            parts.append('ctx.ctr == 0' if (bo & 2) else 'ctx.ctr != 0')
        if not (bo & 0x10):
            parts.append(f'ctx.cr[{bi}]' if (bo & 8) else f'!ctx.cr[{bi}]')
        return pre, (' && '.join(parts) if parts else 'true')

    def goto(self, a, t):
        """Code for an unconditional jump from a to t (inside or outside)."""
        if self.inside(t):
            self.labels.add(t)
            chk = 'PPC_CHECK_IRQ(); ' if t <= a else ''
            return f'{{ {chk}goto loc_{t + self.delta:08X}; }}'
        return self.tailcall(t)

    # ---------------------------------------------------------------- main
    def gen_body(self):
        """The function's statements (one entry per instruction)."""
        # first pass: labels
        for a in range(self.start, self.end, 4):
            ins = decode(self.dol.read32(a))
            if ins.op in ('b', 'bc') and not ins.lk:
                t = (ins.li if ins.aa else a + ins.li) if ins.op == 'b' else (ins.bd if ins.aa else a + ins.bd)
                t &= 0xFFFFFFFF
                if self.inside(t):
                    self.labels.add(t)
            for t in self.jt.get(a, ()):
                if self.inside(t):
                    self.labels.add(t)
        body = []
        self.out = body
        last_term = False
        for a in range(self.start, self.end, 4):
            w = self.dol.read32(a)
            if a in self.labels:
                body.append(f'loc_{a + self.delta:08X}:')
            ins = decode(w)
            last_term = self.insn(a, ins)
        if not last_term:
            # falls through into the next function
            self.emit(self.tailcall(self.end))
        return body

    def gen(self, body=None, pre=''):
        """The C++ function: body (default gen_body()), after the statement pre."""
        if body is None:
            body = self.gen_body()
        name = self.f.get('name')
        hdr = f'// {name}\n' if name else ''
        macro = 'PPC_FUNC_IMPL' if self.start in self.rc.overrides else 'PPC_FUNC'
        if any(self.start <= pa < self.end for pa in self.rc.patches):
            hdr = 'extern "C" uint32_t g_cfgFrameRate;\n' + hdr
        prologue = 'PPC_FUNC_PROLOGUE();'
        if any('PPC_SEL(' in s for s in body):
            prologue += ' PPC_SEL_PROLOGUE();'
        return (hdr + f'{macro}({self.rc.def_sym(self.start)}) {{\n\t{prologue} PPC_COUNT_CALL(0x{self.start:08X});\n'
                + pre + '\n'.join(body) + '\n}\n')

    def insn(self, a, i):
        """Emit one instruction. Returns True if control never falls through."""
        if a in self.rc.probes:
            n, reg = self.rc.probes[a]
            self.emit(f'g_tasProbe[{n}] = ctx.r[{reg}];   // read-only test probe')
        if a in self.rc.patches:
            self.emit(self.rc.patches[a])
            return False
        op = i.op
        e = self.emit
        R = self.r
        nxt = a + 4

        # ------------------------------------------------------ branches
        if op == 'b':
            t = ((i.li if i.aa else a + i.li) & 0xFFFFFFFF)
            if i.lk:
                if t == nxt:
                    e(f'ctx.lr = {h(nxt)};')
                    return False
                if self.rc.is_func(t):
                    self.call(t, nxt)
                else:
                    e(f'ctx.lr = {h(nxt)}; PPC_CALL_INDIRECT({h(t)});')
                return False
            e(self.goto(a, t))
            return True
        if op == 'bc':
            t = ((i.bd if i.aa else a + i.bd) & 0xFFFFFFFF)
            pre, c = self.cond(i.bo, i.bi)
            if i.lk:
                if self.rc.is_func(t):
                    self.calls.add(t)
                    e(f'{pre}if ({c}) {{ ctx.lr = {h(nxt)}; {self.rc.sym(t)}(ctx, base); }}')
                else:
                    e(f'{pre}if ({c}) {{ ctx.lr = {h(nxt)}; PPC_CALL_INDIRECT({h(t)}); }}')
                return False
            if c == 'true':
                e(pre + self.goto(a, t))
                return True
            e(f'{pre}if ({c}) {self.goto(a, t)}')
            return False
        if op == 'bclr':
            pre, c = self.cond(i.bo, i.bi)
            if i.lk:
                e(f'{pre}if ({c}) {{ uint32_t t_ = ctx.lr; ctx.lr = {h(nxt)}; PPC_CALL_INDIRECT(t_); }}')
                return False
            if c == 'true':
                e(pre + 'return;')
                return True
            e(f'{pre}if ({c}) return;')
            return False
        if op == 'bcctr':
            pre, c = self.cond(i.bo, i.bi)
            if i.lk:
                e(f'{pre}if ({c}) {{ ctx.lr = {h(nxt)}; PPC_CALL_INDIRECT(ctx.ctr); }}')
                return False
            if a in self.jt:
                sw = f'(uint32_t)(ctx.ctr + {h(self.delta)})' if self.delta else 'ctx.ctr'
                lines = [f'switch ({sw}) {{']
                for t in sorted(set(self.jt[a])):
                    lines.append(f'\tcase {h(t + self.delta)}: {self.goto(a, t)}')
                lines.append(f'\tdefault: {{ PPC_CALL_INDIRECT(ctx.ctr); return; }}')
                lines.append('\t}')
                body = '\n\t'.join(lines)
                if c != 'true':
                    e(f'{pre}if ({c}) {{\n\t{body}\n\t}}')
                    return False
                e(pre + body)
                return True
            if c == 'true':
                e(pre + '{ PPC_CALL_INDIRECT(ctx.ctr); return; }')
                return True
            e(f'{pre}if ({c}) {{ PPC_CALL_INDIRECT(ctx.ctr); return; }}')
            return False
        if op == 'rfi':
            e('ppc_rfi(ctx, base); return;')
            return True
        if op == 'sc':
            e(f'ppc_sc(ctx, base, {h(a)});')
            return False

        # ------------------------------------------------------ integer arith
        d, A, B = i.rd, i.ra, i.rb
        rc = i.rc
        if op == 'addi':
            if A == 0:
                e(f'{R(d)} = {h(i.simm)};')
            else:
                e(f'{R(d)} = {R(A)} + {h(i.simm)};')
            return False
        if op == 'addis':
            v = (i.simm << 16) & 0xFFFFFFFF
            if A == 0:
                e(f'{R(d)} = {h(v)};')
            else:
                e(f'{R(d)} = {R(A)} + {h(v)};')
            return False
        if op in ('addic', 'addic.'):
            e(f'{{ uint64_t t_ = (uint64_t){R(A)} + {h(i.simm)}u; {R(d)} = (uint32_t)t_; ctx.xer_ca = (uint8_t)(t_ >> 32); }}')
            if op == 'addic.':
                self.cr_record(R(d))
            return False
        if op == 'subfic':
            e(f'{{ uint64_t t_ = (uint64_t)(uint32_t)~{R(A)} + {h(i.simm)}u + 1; {R(d)} = (uint32_t)t_; ctx.xer_ca = (uint8_t)(t_ >> 32); }}')
            return False
        if op == 'mulli':
            e(f'{R(d)} = (uint32_t)((int32_t){R(A)} * {i.simm});')
            return False
        if op in ('cmpi', 'cmpli', 'cmp', 'cmpl'):
            f_ = i.crfd
            if op == 'cmpi':
                e(f'PPC_CMPS({f_}, (int32_t){R(A)}, {i.simm});')
            elif op == 'cmpli':
                e(f'PPC_CMPU({f_}, {R(A)}, {h(i.uimm)}u);')
            elif op == 'cmp':
                e(f'PPC_CMPS({f_}, (int32_t){R(A)}, (int32_t){R(B)});')
            else:
                e(f'PPC_CMPU({f_}, {R(A)}, {R(B)});')
            return False

        S = i.rs
        if op in ('ori', 'oris', 'xori', 'xoris', 'andi.', 'andis.'):
            v = i.uimm << 16 if op.endswith('is') or op == 'andis.' else i.uimm
            o = {'ori': '|', 'oris': '|', 'xori': '^', 'xoris': '^', 'andi.': '&', 'andis.': '&'}[op]
            if o == '|' and v == 0 and S == A:
                e('PPC_NOP();')
                return False
            e(f'{R(A)} = {R(S)} {o} {h(v)};')
            if op.startswith('and'):
                self.cr_record(R(A))
            return False
        if op in ('rlwinm', 'rlwimi', 'rlwnm'):
            m = mask32(i.mb, i.me)
            if op == 'rlwnm':
                rot = f'ppc_rotl32({R(S)}, {R(B)} & 31)'
            else:
                rot = f'ppc_rotl32({R(S)}, {i.sh})' if i.sh else R(S)
            if op == 'rlwimi':
                e(f'{R(A)} = ({rot} & {h(m)}) | ({R(A)} & {h(~m & 0xFFFFFFFF)});')
            else:
                if m == 0xFFFFFFFF:
                    e(f'{R(A)} = {rot};')
                else:
                    e(f'{R(A)} = {rot} & {h(m)};')
            if rc:
                self.cr_record(R(A))
            return False

        if op in ('add', 'subf', 'addc', 'subfc', 'adde', 'subfe', 'addze', 'subfze',
                  'addme', 'subfme', 'neg', 'mullw', 'mulhw', 'mulhwu', 'divw', 'divwu'):
            if op == 'add':
                e(f'{R(d)} = {R(A)} + {R(B)};')
            elif op == 'subf':
                e(f'{R(d)} = {R(B)} - {R(A)};')
            elif op == 'addc':
                e(f'{{ uint64_t t_ = (uint64_t){R(A)} + {R(B)}; {R(d)} = (uint32_t)t_; ctx.xer_ca = (uint8_t)(t_ >> 32); }}')
            elif op == 'subfc':
                e(f'{{ uint64_t t_ = (uint64_t)(uint32_t)~{R(A)} + {R(B)} + 1; {R(d)} = (uint32_t)t_; ctx.xer_ca = (uint8_t)(t_ >> 32); }}')
            elif op == 'adde':
                e(f'{{ uint64_t t_ = (uint64_t){R(A)} + {R(B)} + ctx.xer_ca; {R(d)} = (uint32_t)t_; ctx.xer_ca = (uint8_t)(t_ >> 32); }}')
            elif op == 'subfe':
                e(f'{{ uint64_t t_ = (uint64_t)(uint32_t)~{R(A)} + {R(B)} + ctx.xer_ca; {R(d)} = (uint32_t)t_; ctx.xer_ca = (uint8_t)(t_ >> 32); }}')
            elif op == 'addze':
                e(f'{{ uint64_t t_ = (uint64_t){R(A)} + ctx.xer_ca; {R(d)} = (uint32_t)t_; ctx.xer_ca = (uint8_t)(t_ >> 32); }}')
            elif op == 'subfze':
                e(f'{{ uint64_t t_ = (uint64_t)(uint32_t)~{R(A)} + ctx.xer_ca; {R(d)} = (uint32_t)t_; ctx.xer_ca = (uint8_t)(t_ >> 32); }}')
            elif op == 'addme':
                e(f'{{ uint64_t t_ = (uint64_t){R(A)} + ctx.xer_ca + 0xFFFFFFFFull; {R(d)} = (uint32_t)t_; ctx.xer_ca = (uint8_t)(t_ >> 32); }}')
            elif op == 'subfme':
                e(f'{{ uint64_t t_ = (uint64_t)(uint32_t)~{R(A)} + ctx.xer_ca + 0xFFFFFFFFull; {R(d)} = (uint32_t)t_; ctx.xer_ca = (uint8_t)(t_ >> 32); }}')
            elif op == 'neg':
                e(f'{R(d)} = (uint32_t)(-(int32_t){R(A)});')
            elif op == 'mullw':
                e(f'{R(d)} = (uint32_t)((int32_t){R(A)} * (int32_t){R(B)});')
            elif op == 'mulhw':
                e(f'{R(d)} = (uint32_t)(((int64_t)(int32_t){R(A)} * (int64_t)(int32_t){R(B)}) >> 32);')
            elif op == 'mulhwu':
                e(f'{R(d)} = (uint32_t)(((uint64_t){R(A)} * (uint64_t){R(B)}) >> 32);')
            elif op == 'divw':
                e(f'{R(d)} = ppc_divw({R(A)}, {R(B)});')
            elif op == 'divwu':
                e(f'{R(d)} = ppc_divwu({R(A)}, {R(B)});')
            if i.oe:
                e(f'/* OE ignored */')
            if rc:
                self.cr_record(R(d))
            return False

        if op in ('and', 'or', 'xor', 'nand', 'nor', 'eqv', 'andc', 'orc', 'slw', 'srw',
                  'sraw', 'srawi', 'cntlzw', 'extsb', 'extsh'):
            if op == 'or' and S == B:
                if S == A:
                    e('PPC_NOP();')
                else:
                    e(f'{R(A)} = {R(S)};')
            elif op in ('and', 'or', 'xor'):
                o = {'and': '&', 'or': '|', 'xor': '^'}[op]
                e(f'{R(A)} = {R(S)} {o} {R(B)};')
            elif op == 'nand':
                e(f'{R(A)} = ~({R(S)} & {R(B)});')
            elif op == 'nor':
                e(f'{R(A)} = ~({R(S)} | {R(B)});')
            elif op == 'eqv':
                e(f'{R(A)} = ~({R(S)} ^ {R(B)});')
            elif op == 'andc':
                e(f'{R(A)} = {R(S)} & ~{R(B)};')
            elif op == 'orc':
                e(f'{R(A)} = {R(S)} | ~{R(B)};')
            elif op == 'slw':
                e(f'{R(A)} = ({R(B)} & 0x20) ? 0 : ({R(S)} << ({R(B)} & 31));')
            elif op == 'srw':
                e(f'{R(A)} = ({R(B)} & 0x20) ? 0 : ({R(S)} >> ({R(B)} & 31));')
            elif op == 'sraw':
                e(f'{R(A)} = ppc_sraw(ctx, {R(S)}, {R(B)});')
            elif op == 'srawi':
                n = i.sh
                if n == 0:
                    e(f'{R(A)} = {R(S)}; ctx.xer_ca = 0;')
                else:
                    e(f'{{ uint32_t s_ = {R(S)}; ctx.xer_ca = ((int32_t)s_ < 0) && (s_ & {h((1 << n) - 1)}); {R(A)} = (uint32_t)((int32_t)s_ >> {n}); }}')
            elif op == 'cntlzw':
                e(f'{R(A)} = ppc_cntlzw({R(S)});')
            elif op == 'extsb':
                e(f'{R(A)} = (uint32_t)(int32_t)(int8_t){R(S)};')
            elif op == 'extsh':
                e(f'{R(A)} = (uint32_t)(int32_t)(int16_t){R(S)};')
            if rc:
                self.cr_record(R(A))
            return False

        # ------------------------------------------------------ loads / stores
        p = i.w >> 26
        if 32 <= p <= 45 or 48 <= p <= 55:
            upd = op.endswith('u')
            base_op = op[:-1] if upd else op
            if A == 0:
                ea = h(i.simm)
            elif i.simm:
                ea = f'{R(A)} + {h(i.simm)}'
            else:
                ea = R(A)
            return self.ldst(base_op, upd, d, A, ea)
        if p == 31 and op in X_LDST:
            base_op, upd = X_LDST[op]
            ea = f'{R(A)} + {R(B)}' if A else R(B)
            return self.ldst(base_op, upd, d, A, ea, idx_base=(A if A else B))
        if op == 'lmw':
            ea = f'{self.ra0(A)} + {h(i.simm)}'
            e(f'ea = {ea};')
            for k, reg in enumerate(range(d, 32)):
                e(f'{R(reg)} = {self.ld(4, f"ea + {4 * k}", A)};')
            return False
        if op == 'stmw':
            ea = f'{self.ra0(A)} + {h(i.simm)}'
            e(f'ea = {ea};')
            for k, reg in enumerate(range(d, 32)):
                e(self.st(4, f'ea + {4 * k}', R(reg), A))
            return False
        if op == 'lswi':
            e(f'ppc_lswi(ctx, base, {self.ra0(A)}, {d}, {i.nb});')
            return False
        if op == 'stswi':
            e(f'ppc_stswi(ctx, base, {self.ra0(A)}, {d}, {i.nb});')
            return False
        if op == 'lswx':
            e(f'ppc_lswx(ctx, base, {self.ra0(A)} + {R(B)}, {d});')
            return False
        if op == 'stswx':
            e(f'ppc_stswx(ctx, base, {self.ra0(A)} + {R(B)}, {d});')
            return False
        if op == 'lwarx':
            e(f'ea = {self.ra0(A)} + {R(B)}; ctx.reserve = 1; ctx.reserve_addr = ea; {R(d)} = {self.ld(4, "ea", -1)};')
            return False
        if op == 'stwcx.':
            e(f'ea = {self.ra0(A)} + {R(B)}; {self.st(4, "ea", R(S), -1)} ctx.cr[0] = 0; ctx.cr[1] = 0; ctx.cr[2] = 1; ctx.cr[3] = ctx.xer_so; ctx.reserve = 0;')
            return False

        # paired single loads/stores
        if op in ('psq_l', 'psq_lu', 'psq_st', 'psq_stu'):
            ea = f'{self.ra0(A)} + {h(i.ps_d)}' if not (op.endswith('u')) else f'{R(A)} + {h(i.ps_d)}'
            e(f'ea = {ea};')
            if op.startswith('psq_l'):
                e(f'ppc_psq_load(ctx, base, ea, {i.ps_w}, {i.ps_i}, {d});')
            else:
                e(f'ppc_psq_store(ctx, base, ea, {i.ps_w}, {i.ps_i}, {d});')
            if op.endswith('u'):
                e(f'{R(A)} = ea;')
            return False
        if op in ('psq_lx', 'psq_lux', 'psq_stx', 'psq_stux'):
            upd = op.endswith('ux')
            ea = f'{R(A)} + {R(B)}' if (A or upd) else R(B)
            e(f'ea = {ea};')
            if op.startswith('psq_l'):
                e(f'ppc_psq_load(ctx, base, ea, {i.psx_w}, {i.psx_i}, {d});')
            else:
                e(f'ppc_psq_store(ctx, base, ea, {i.psx_w}, {i.psx_i}, {d});')
            if upd:
                e(f'{R(A)} = ea;')
            return False

        # ------------------------------------------------------ cache / sync
        if op in ('dcbf', 'dcbst', 'dcbt', 'dcbtst', 'icbi', 'sync', 'isync', 'eieio',
                  'tlbie', 'tlbsync', 'tlbia', 'eciwx', 'ecowx'):
            e(f'PPC_NOP(); // {op}')
            return False
        if op == 'dcbi':
            e(f'ppc_dcbi(base, {self.ra0(A)} + {R(B)});')
            return False
        if op in ('dcbz', 'dcbz_l'):
            e(f'ppc_dcbz(base, {self.ra0(A)} + {R(B)});')
            return False

        # ------------------------------------------------------ SPR / MSR / CR
        if op == 'mfspr':
            n = i.spr
            if n == SPR_LR:
                e(f'{R(d)} = ctx.lr;')
            elif n == SPR_CTR:
                e(f'{R(d)} = ctx.ctr;')
            elif n == SPR_XER:
                e(f'{R(d)} = ppc_get_xer(ctx);')
            elif GQR0 <= n < GQR0 + 8:
                e(f'{R(d)} = ctx.gqr[{n - GQR0}];')
            else:
                e(f'{R(d)} = ppc_mfspr(ctx, {n});')
            return False
        if op == 'mtspr':
            n = i.spr
            if n == SPR_LR:
                e(f'ctx.lr = {R(S)};')
            elif n == SPR_CTR:
                e(f'ctx.ctr = {R(S)};')
            elif n == SPR_XER:
                e(f'ppc_set_xer(ctx, {R(S)});')
            elif GQR0 <= n < GQR0 + 8:
                e(f'ctx.gqr[{n - GQR0}] = {R(S)};')
            else:
                e(f'ppc_mtspr(ctx, base, {n}, {R(S)});')
            return False
        if op == 'mftb':
            e(f'{R(d)} = ppc_mftb(ctx, {i.tbr});')
            return False
        if op == 'mfmsr':
            e(f'{R(d)} = ctx.msr;')
            return False
        if op == 'mtmsr':
            e(f'ppc_mtmsr(ctx, base, {R(S)});')
            return False
        if op == 'mfsr':
            e(f'{R(d)} = ctx.sr[{i.sr}];')
            return False
        if op == 'mtsr':
            e(f'ctx.sr[{i.sr}] = {R(S)};')
            return False
        if op == 'mfsrin':
            e(f'{R(d)} = ctx.sr[{R(B)} >> 28];')
            return False
        if op == 'mtsrin':
            e(f'ctx.sr[{R(B)} >> 28] = {R(S)};')
            return False
        if op == 'mfcr':
            e(f'{R(d)} = ppc_get_cr(ctx);')
            return False
        if op == 'mtcrf':
            if i.crm == 0xFF:
                e(f'ppc_set_cr(ctx, {R(S)});')
            else:
                e(f'ppc_mtcrf(ctx, {R(S)}, {h(i.crm)});')
            return False
        if op == 'mcrf':
            df, sf = i.crfd, i.crfs
            e(f'memcpy(&ctx.cr[{4 * df}], &ctx.cr[{4 * sf}], 4);')
            return False
        if op == 'mcrxr':
            df = i.crfd
            e(f'ctx.cr[{4 * df}] = ctx.xer_so; ctx.cr[{4 * df + 1}] = ctx.xer_ov; ctx.cr[{4 * df + 2}] = ctx.xer_ca; ctx.cr[{4 * df + 3}] = 0; ctx.xer_so = ctx.xer_ov = ctx.xer_ca = 0;')
            return False
        if op in ('crand', 'cror', 'crxor', 'crnand', 'crnor', 'creqv', 'crandc', 'crorc'):
            bd, ba, bb = i.crbd, i.crba, i.crbb
            ca, cb = f'ctx.cr[{ba}]', f'ctx.cr[{bb}]'
            expr = {
                'crand': f'{ca} & {cb}', 'cror': f'{ca} | {cb}', 'crxor': f'{ca} ^ {cb}',
                'crnand': f'!({ca} & {cb})', 'crnor': f'!({ca} | {cb})',
                'creqv': f'!({ca} ^ {cb})', 'crandc': f'{ca} & !{cb}', 'crorc': f'{ca} | !{cb}',
            }[op]
            if op == 'crxor' and ba == bb:
                expr = '0'
            if op == 'creqv' and ba == bb:
                expr = '1'
            e(f'ctx.cr[{bd}] = (uint8_t)({expr});')
            return False
        if op in ('tw', 'twi'):
            b_ = R(B) if op == 'tw' else h(i.simm)
            e(f'ppc_trap(ctx, base, {h(a)}, {i.to}, {R(A)}, {b_});')
            return False

        # ------------------------------------------------------ floating point
        if p in (59, 63):
            return self.fpu(a, i)
        if p == 4:
            return self.paired(a, i)

        e(f'ppc_illegal(ctx, base, {h(a)}, {h(i.w)});')
        return False

    def ldst(self, op, upd, d, A, ea, idx_base=None):
        e = self.emit
        R = self.r
        breg = A if idx_base is None else idx_base
        if upd and A == 0:
            breg = -1
        e(f'ea = {ea};')
        if op == 'lwz':
            e(f'{R(d)} = {self.ld(4, "ea", breg)};')
        elif op == 'lhz':
            e(f'{R(d)} = {self.ld(2, "ea", breg)};')
        elif op == 'lha':
            e(f'{R(d)} = {self.ld(2, "ea", breg, signed=True)};')
        elif op == 'lbz':
            e(f'{R(d)} = {self.ld(1, "ea", breg)};')
        elif op == 'stw':
            e(self.st(4, 'ea', R(d), breg))
        elif op == 'sth':
            e(self.st(2, 'ea', R(d), breg))
        elif op == 'stb':
            e(self.st(1, 'ea', R(d), breg))
        elif op == 'lwbrx':
            e(f'{R(d)} = ppc_bswap32({self.ld(4, "ea", breg)});')
        elif op == 'lhbrx':
            e(f'{R(d)} = ppc_bswap16((uint16_t){self.ld(2, "ea", breg)});')
        elif op == 'stwbrx':
            e(self.st(4, 'ea', f'ppc_bswap32({R(d)})', breg))
        elif op == 'sthbrx':
            e(self.st(2, 'ea', f'ppc_bswap16((uint16_t){R(d)})', breg))
        elif op == 'lfs':
            e(f'{{ double v_ = (double)ldf32(base, ea); ctx.f[{d}].f64 = v_; ctx.f[{d}].ps1 = v_; }}')
        elif op == 'lfd':
            e(f'ctx.f[{d}].u64 = ld64(base, ea);')
        elif op == 'stfs':
            e(f'stf32(base, ea, (float)ctx.f[{d}].f64);')
        elif op == 'stfd':
            e(f'st64(base, ea, ctx.f[{d}].u64);')
        elif op == 'stfiwx':
            e(f'st32(base, ea, (uint32_t)ctx.f[{d}].u64);')
        else:
            raise ValueError(op)
        if upd:
            e(f'{R(A)} = ea;')
        return False

    def fpu(self, a, i):
        e = self.emit
        op = i.op
        d, A, B, C = i.frd, i.fra, i.frb, i.frc
        F = self.fr
        single = (i.w >> 26) == 59
        arith = {
            'fadd': f'{F(A)} + {F(B)}', 'fsub': f'{F(A)} - {F(B)}',
            'fmul': f'{F(A)} * {F(C)}', 'fdiv': f'{F(A)} / {F(B)}',
            'fmadd': f'{F(A)} * {F(C)} + {F(B)}', 'fmsub': f'{F(A)} * {F(C)} - {F(B)}',
            'fnmadd': f'-({F(A)} * {F(C)} + {F(B)})', 'fnmsub': f'-({F(A)} * {F(C)} - {F(B)})',
            'fsqrt': f'sqrt({F(B)})',
        }
        base_op = op[:-1] if single else op
        if base_op in arith:
            ex = arith[base_op]
            if single:
                e(f'{{ double v_ = (double)(float)({ex}); ctx.f[{d}].f64 = v_; ctx.f[{d}].ps1 = v_; }}')
            else:
                e(f'{F(d)} = {ex};')
        elif op == 'fres':
            e(f'{{ double v_ = ppc_fres({F(B)}); ctx.f[{d}].f64 = v_; ctx.f[{d}].ps1 = v_; }}')
        elif op == 'frsqrte':
            e(f'{F(d)} = ppc_frsqrte({F(B)});')
        elif op == 'fsel':
            e(f'{F(d)} = ({F(A)} >= 0.0) ? {F(C)} : {F(B)};')
        elif op in ('fcmpu', 'fcmpo'):
            e(f'PPC_FCMP({i.crfd}, {F(A)}, {F(B)});')
            return False
        elif op == 'frsp':
            e(f'{{ double v_ = (double)(float){F(B)}; ctx.f[{d}].f64 = v_; ctx.f[{d}].ps1 = v_; }}')
        elif op == 'fctiw':
            e(f'ctx.f[{d}].u64 = ppc_fctiw(ctx, {F(B)});')
        elif op == 'fctiwz':
            e(f'ctx.f[{d}].u64 = ppc_fctiwz({F(B)});')
        elif op == 'fmr':
            e(f'ctx.f[{d}].u64 = ctx.f[{B}].u64;')
        elif op == 'fneg':
            e(f'ctx.f[{d}].u64 = ctx.f[{B}].u64 ^ 0x8000000000000000ull;')
        elif op == 'fabs':
            e(f'ctx.f[{d}].u64 = ctx.f[{B}].u64 & 0x7FFFFFFFFFFFFFFFull;')
        elif op == 'fnabs':
            e(f'ctx.f[{d}].u64 = ctx.f[{B}].u64 | 0x8000000000000000ull;')
        elif op == 'mffs':
            e(f'ctx.f[{d}].u64 = 0xFFF8000000000000ull | ctx.fpscr;')
        elif op == 'mtfsf':
            e(f'ppc_mtfsf(ctx, {h(i.fm)}, (uint32_t)ctx.f[{B}].u64);')
        elif op == 'mtfsb0':
            e(f'ctx.fpscr &= ~(0x80000000u >> {d});')
        elif op == 'mtfsb1':
            e(f'ctx.fpscr |= (0x80000000u >> {d});')
        elif op == 'mtfsfi':
            imm = (i.w >> 12) & 15
            sh = 28 - 4 * i.crfd
            e(f'ctx.fpscr = (ctx.fpscr & ~(0xFu << {sh})) | ({imm}u << {sh});')
        elif op == 'mcrfs':
            sf = i.crfs
            df = i.crfd
            sh = 28 - 4 * sf
            e(f'{{ uint32_t v_ = (ctx.fpscr >> {sh}) & 0xF; ctx.cr[{4 * df}] = (v_ >> 3) & 1; ctx.cr[{4 * df + 1}] = (v_ >> 2) & 1; ctx.cr[{4 * df + 2}] = (v_ >> 1) & 1; ctx.cr[{4 * df + 3}] = v_ & 1; }}')
            return False
        else:
            e(f'ppc_illegal(ctx, base, {h(a)}, {h(i.w)});')
            return False
        if i.rc:
            e('PPC_CR1();')
        return False

    def paired(self, a, i):
        e = self.emit
        op = i.op
        d, A, B, C = i.frd, i.fra, i.frb, i.frc
        a0, a1 = f'ctx.f[{A}].f64', f'ctx.f[{A}].ps1'
        b0, b1 = f'ctx.f[{B}].f64', f'ctx.f[{B}].ps1'
        c0, c1 = f'ctx.f[{C}].f64', f'ctx.f[{C}].ps1'

        def setps(x0, x1, rnd=True):
            if rnd:
                e(f'{{ double p0_ = (double)(float)({x0}); double p1_ = (double)(float)({x1}); ctx.f[{d}].f64 = p0_; ctx.f[{d}].ps1 = p1_; }}')
            else:
                e(f'{{ double p0_ = {x0}; double p1_ = {x1}; ctx.f[{d}].f64 = p0_; ctx.f[{d}].ps1 = p1_; }}')

        if op == 'ps_add':
            setps(f'{a0} + {b0}', f'{a1} + {b1}')
        elif op == 'ps_sub':
            setps(f'{a0} - {b0}', f'{a1} - {b1}')
        elif op == 'ps_mul':
            setps(f'{a0} * {c0}', f'{a1} * {c1}')
        elif op == 'ps_div':
            setps(f'{a0} / {b0}', f'{a1} / {b1}')
        elif op == 'ps_madd':
            setps(f'{a0} * {c0} + {b0}', f'{a1} * {c1} + {b1}')
        elif op == 'ps_msub':
            setps(f'{a0} * {c0} - {b0}', f'{a1} * {c1} - {b1}')
        elif op == 'ps_nmadd':
            setps(f'-({a0} * {c0} + {b0})', f'-({a1} * {c1} + {b1})')
        elif op == 'ps_nmsub':
            setps(f'-({a0} * {c0} - {b0})', f'-({a1} * {c1} - {b1})')
        elif op == 'ps_muls0':
            setps(f'{a0} * {c0}', f'{a1} * {c0}')
        elif op == 'ps_muls1':
            setps(f'{a0} * {c1}', f'{a1} * {c1}')
        elif op == 'ps_madds0':
            setps(f'{a0} * {c0} + {b0}', f'{a1} * {c0} + {b1}')
        elif op == 'ps_madds1':
            setps(f'{a0} * {c1} + {b0}', f'{a1} * {c1} + {b1}')
        elif op == 'ps_sum0':
            setps(f'{a0} + {b1}', c1)
        elif op == 'ps_sum1':
            setps(c0, f'{a0} + {b1}')
        elif op == 'ps_sel':
            setps(f'({a0} >= 0.0) ? {c0} : {b0}', f'({a1} >= 0.0) ? {c1} : {b1}', rnd=False)
        elif op == 'ps_res':
            setps(f'ppc_fres({b0})', f'ppc_fres({b1})', rnd=False)
        elif op == 'ps_rsqrte':
            setps(f'(double)(float)ppc_frsqrte({b0})', f'(double)(float)ppc_frsqrte({b1})', rnd=False)
        elif op == 'ps_mr':
            setps(b0, b1, rnd=False)
        elif op == 'ps_neg':
            setps(f'-{b0}', f'-{b1}', rnd=False)
        elif op == 'ps_abs':
            setps(f'fabs({b0})', f'fabs({b1})', rnd=False)
        elif op == 'ps_nabs':
            setps(f'-fabs({b0})', f'-fabs({b1})', rnd=False)
        elif op == 'ps_merge00':
            setps(a0, b0, rnd=False)
        elif op == 'ps_merge01':
            setps(a0, b1, rnd=False)
        elif op == 'ps_merge10':
            setps(a1, b0, rnd=False)
        elif op == 'ps_merge11':
            setps(a1, b1, rnd=False)
        elif op in ('ps_cmpu0', 'ps_cmpo0'):
            e(f'PPC_FCMP({i.crfd}, {a0}, {b0});')
            return False
        elif op in ('ps_cmpu1', 'ps_cmpo1'):
            e(f'PPC_FCMP({i.crfd}, {a1}, {b1});')
            return False
        elif op == 'dcbz_l':
            e(f'ppc_dcbz(base, {self.ra0(A)} + ctx.r[{B}]);')
            return False
        else:
            e(f'ppc_illegal(ctx, base, {h(a)}, {h(i.w)});')
            return False
        if i.rc:
            e('PPC_CR1();')
        return False


# Read-only test probes (address -> (slot, register)): record a register, usually an
# object's address, into g_tasProbe[slot] before the instruction runs, for TAS-script
# telemetry (docs/tas.md). They change no guest state.
PROBES = {
}

# Instruction replacements (address -> C++). Used for runtime-configurable tweaks.
PATCHES = {
    0x800B6878: 'ctx.r[0] = g_cfgFrameRate;   // li r0,30: target frame rate (30 or 60)',
}

X_LDST = {
    'lwzx': ('lwz', False), 'lwzux': ('lwz', True), 'lbzx': ('lbz', False), 'lbzux': ('lbz', True),
    'lhzx': ('lhz', False), 'lhzux': ('lhz', True), 'lhax': ('lha', False), 'lhaux': ('lha', True),
    'stwx': ('stw', False), 'stwux': ('stw', True), 'stbx': ('stb', False), 'stbux': ('stb', True),
    'sthx': ('sth', False), 'sthux': ('sth', True), 'lwbrx': ('lwbrx', False), 'lhbrx': ('lhbrx', False),
    'stwbrx': ('stwbrx', False), 'sthbrx': ('sthbrx', False), 'lfsx': ('lfs', False), 'lfsux': ('lfs', True),
    'lfdx': ('lfd', False), 'lfdux': ('lfd', True), 'stfsx': ('stfs', False), 'stfsux': ('stfs', True),
    'stfdx': ('stfd', False), 'stfdux': ('stfd', True), 'stfiwx': ('stfiwx', False),
}


def write_if_changed(path, text):
    try:
        with open(path, 'r', newline='\n') as fp:
            if fp.read() == text:
                return False
    except FileNotFoundError:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)   # fresh checkout
    with open(path, 'w', newline='\n') as fp:
        fp.write(text)
    return True


# Statements of two builds' versions of a function merge when they differ only in
# values: numbers (data and return addresses) and callees.
TOKEN = re.compile(r'0x[0-9A-Fa-f]+u?|-?\d+u?|\w+|\s+|.', re.S)
NUMBER = re.compile(r'-?(?:0x[0-9A-Fa-f]+|\d+)u?$')
CALLEE = re.compile(r'(?:eu_)?fn_[0-9A-F]{8}$')
EU_SWITCH = re.compile(r'switch \(\(uint32_t\)\(ctx\.ctr \+ (0x[0-9A-F]+)\)\)')


def merge_stmt(a, b):
    """One statement for both builds (b: the European one), or None."""
    if a == b:
        return a
    sw = EU_SWITCH.search(b)
    if sw:   # jump table: the European ctr is mapped onto the shared case labels
        b = b.replace(sw[0], 'switch (ctx.ctr)', 1)
    ta, tb = TOKEN.findall(a), TOKEN.findall(b)
    if len(ta) != len(tb):
        return None
    out = []
    for x, y in zip(ta, tb):
        if x == y:
            out.append(x)
        elif (NUMBER.match(x) and NUMBER.match(y)) or (CALLEE.match(x) and CALLEE.match(y)):
            out.append(f'PPC_SEL({x}, {y})')
        else:
            return None
    s = ''.join(out)
    if 'case PPC_SEL(' in s:   # a jump-table target in another function: no constant
        return None
    if sw:
        s = s.replace('switch (ctx.ctr)', f'switch (PPC_SEL(ctx.ctr, (uint32_t)(ctx.ctr + {sw[1]})))', 1)
    return s


def merge_body(a, b):
    if len(a) != len(b):
        return None
    out = []
    for x, y in zip(a, b):
        m = merge_stmt(x, y)
        if m is None:
            return None
        out.append(m)
    return out


class Recompiler:
    def __init__(self, dol, funcs, overrides=(), patches=None, probes=None, prefix='', names=None):
        self.dol = dol
        self.funcs = funcs
        self.starts = {f['start'] for f in funcs}
        self.overrides = set(overrides)
        self.patches = PATCHES if patches is None else patches
        self.probes = PROBES if probes is None else probes
        self.prefix = prefix
        self.names = names or {}   # function start -> name its callers use, if not def_sym

    def sym(self, a):
        """What a call to the function at a calls: the runtime's override, or the recompiled code."""
        return self.names.get(a) or self.def_sym(a)

    def def_sym(self, a):
        """Name of the recompiled body of the function at a (plus _impl if overridden)."""
        return f'{self.prefix}fn_{a:08X}'

    def is_func(self, a):
        return a in self.starts

    def run(self, outdir, eu=None, per_file=6000):
        """eu: (Recompiler of the European build, {start: European start} of matched
        functions, its output directory). A matched pair is emitted once, under the base
        build's name, when the two merge; otherwise the shared name runs the European
        body (eu_fn_<European start>) in that release."""
        eu_rc, match, eu_dir = eu if eu else (None, {}, None)
        eu_own = []
        shared = 0
        files = []
        chunk, count, idx = [], 0, 0

        def flush(d, fl, include):
            nonlocal chunk, count, idx
            if not chunk:
                return
            name = f'ppc_recomp.{idx}.cpp'
            write_if_changed(os.path.join(d, name), f'#include "{include}"\n\n' + ''.join(chunk))
            fl.append(name)
            chunk, count = [], 0
            idx += 1

        for f in self.funcs:
            g = FuncGen(self, f)
            e = match.get(f['start'])
            if e is None:
                text = g.gen()
            else:
                ef = eu_rc.func_at[e]
                eg = FuncGen(eu_rc, ef)
                eg.delta = f['start'] - e
                body = g.gen_body()
                merged = merge_body(body, eg.gen_body())
                if merged is not None:
                    text = g.gen(merged)
                    shared += 1
                else:
                    text = g.gen(body, f'\tif (g_ppcEuCode) {{ {eu_rc.def_sym(e)}(ctx, base); return; }}\n')
                    eu_own.append(ef)
            chunk.append(text + '\n')
            count += (f['end'] - f['start']) // 4
            if count >= per_file:
                flush(outdir, files, 'ppc_recomp_shared.h')
        flush(outdir, files, 'ppc_recomp_shared.h')

        hdr = ['#pragma once\n#include "ppc_context.h"\n\n']
        for f in self.funcs:
            a = f['start']
            hdr.append(f'PPC_EXTERN_FUNC({self.sym(a)}); PPC_EXTERN_FUNC({self.def_sym(a)}_impl);\n')
        if eu:
            matched = set(match.values())
            eu_own += [f for f in eu_rc.funcs if f['start'] not in matched]
            eu_own.sort(key=lambda f: f['start'])
            for f in eu_own:
                hdr.append(f'PPC_EXTERN_FUNC({eu_rc.def_sym(f["start"])});\n')
        write_if_changed(os.path.join(outdir, 'ppc_recomp_shared.h'), ''.join(hdr))

        write_table(self, outdir, 'PPCFuncMappings', 'ppc_recomp_shared.h')

        sym = ['#pragma once\n// Known symbol addresses\n']
        seen = set()
        for f in self.funcs:
            n = f.get('name') or f.get('sym')
            if not n:
                continue
            cid = ''.join(c if c.isalnum() or c == '_' else '_' for c in n)
            if cid in seen:
                continue
            seen.add(cid)
            sym.append(f'#define SYM_{cid} 0x{f["start"]:08X}\n')
        write_if_changed(os.path.join(outdir, 'ppc_symbols.h'), ''.join(sym))
        write_sources(outdir, files, '')

        if eu:
            eu_files, idx = [], 0
            for f in eu_own:
                chunk.append(FuncGen(eu_rc, f).gen() + '\n')
                count += (f['end'] - f['start']) // 4
                if count >= per_file:
                    flush(eu_dir, eu_files, '../ppc_recomp_shared.h')
            flush(eu_dir, eu_files, '../ppc_recomp_shared.h')
            write_table(eu_rc, eu_dir, 'PPCFuncMappings_eu', '../ppc_recomp_shared.h')
            write_sources(eu_dir, eu_files, '_EU')
            keep = set(eu_files) | {'ppc_func_mapping.cpp', 'sources.cmake'}
            for n in os.listdir(eu_dir):   # earlier layouts generated more here
                if n not in keep:
                    os.remove(os.path.join(eu_dir, n))
            print(f'European build: {shared} functions shared with the base build, '
                  f'{len(eu_own)} of its own', file=sys.stderr)
        return files


def write_table(rc, outdir, table, include):
    m = [f'#include "{include}"\n\nextern "C" const PPCFuncMapping {table}[] = {{\n']
    for f in rc.funcs:
        m.append(f'\t{{ 0x{f["start"]:08X}, {rc.sym(f["start"])} }},\n')
    m.append('\t{ 0, nullptr }\n};\n')
    write_if_changed(os.path.join(outdir, 'ppc_func_mapping.cpp'), ''.join(m))


def write_sources(outdir, files, suffix):
    src = [f'set(PPC_RECOMP_SOURCES{suffix}\n']
    for n in files + ['ppc_func_mapping.cpp']:
        src.append(f'\t${{CMAKE_CURRENT_LIST_DIR}}/{n}\n')
    src.append(')\n')
    write_if_changed(os.path.join(outdir, 'sources.cmake'), ''.join(src))


def european_build(dol, funcs, overrides, eu_dol_path, eu_funcs_path):
    """Recompiler for the European main.dol and its {base start: European start} matches.
    Its matched functions are called by the base build's names (the runtime's overrides
    included); the rest are eu_fn_<address>."""
    from regions import AddrMap, match_functions
    eu_dol = Dol(eu_dol_path)
    eu_funcs = json.load(open(eu_funcs_path))
    match = match_functions(dol, funcs, eu_dol, eu_funcs)
    amap = AddrMap(funcs, match)
    missing = [a for a in overrides if dol.is_text(a) and a not in match]
    patches = {}
    for a, s in PATCHES.items():
        m = amap(a)
        if m is None:
            missing.append(a)
        else:
            patches[m] = s
    if missing:
        sys.exit('no European counterpart for: ' + ' '.join(f'{a:08X}' for a in missing))
    probes = {amap(a): p for a, p in PROBES.items() if amap(a) is not None}
    rc = Recompiler(eu_dol, eu_funcs, (), patches, probes, 'eu_', {e: f'fn_{b:08X}' for b, e in match.items()})
    rc.func_at = {f['start']: f for f in eu_funcs}
    return rc, match


if __name__ == '__main__':
    eu_args = None
    if '--eu' in sys.argv:
        i = sys.argv.index('--eu')
        eu_args = sys.argv[i + 1:i + 4]
        del sys.argv[i:i + 4]
    dol = Dol(sys.argv[1])
    funcs = json.load(open(sys.argv[2]))
    overrides = []
    if len(sys.argv) > 4:
        overrides = [int(x, 16) for x in open(sys.argv[4]).read().split()]
    eu = None
    if eu_args:
        eu_rc, match = european_build(dol, funcs, overrides, eu_args[0], eu_args[1])
        eu = (eu_rc, match, eu_args[2])
        os.makedirs(eu_args[2], exist_ok=True)
    # Optional: the linked hbm_part.rso module (see tools/rso.py), appended as an extra
    # text section; the runtime only uses it after checking the code in memory.
    rso_info = os.path.join(os.path.dirname(sys.argv[2]), 'rso_info.json')
    rso = None
    if os.path.exists(rso_info):
        from dol import Section
        rso = json.load(open(rso_info))
        img = open(os.path.join(os.path.dirname(sys.argv[2]), 'rso_image.bin'), 'rb').read()
        dol.sections.append(Section('text', 7, 0, rso['text'], img))
        dol.text = [x for x in dol.sections if x.kind == 'text']
        funcs = funcs + json.load(open(os.path.join(os.path.dirname(sys.argv[2]), 'rso_functions.json')))
    info = ['#pragma once\n// hbm_part.rso module recompiled at its boot-time link address (tools/rso.py)\n']
    if rso:
        info.append(f'#define PPC_RSO_TEXT_BEGIN 0x{rso["text"]:08X}u\n#define PPC_RSO_TEXT_END 0x{rso["text"] + rso["size"]:08X}u\n'
                    f'#define PPC_RSO_TEXT_HASH 0x{rso["hash"]:016X}ull\n')
    write_if_changed(os.path.join(sys.argv[3], 'ppc_rso_info.h'), ''.join(info))
    rc = Recompiler(dol, funcs, overrides)
    files = rc.run(sys.argv[3], eu)
    print(f'wrote {len(files)} source files ({len(overrides)} overrides)', file=sys.stderr)
