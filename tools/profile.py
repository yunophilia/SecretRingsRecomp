"""Sampling profiler for a running SecretRingsRecomp.exe (Windows).

  python tools/profile.py [seconds] [--tid N] [--top N]

Samples the busiest thread (or --tid) about 1000 times a second by suspending it and
reading its instruction pointer, then prints the functions it was in, by name from
the exe's PDB. Recompiled game functions show as fn_XXXXXXXX (look them up in
out/functions.json or with tools/xref.py).
"""
import collections
import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
dbg = ctypes.WinDLL('dbghelp', use_last_error=True)

PROCESS_ALL = 0x1F0FFF
THREAD_ALL = 0x1F03FF
CONTEXT_CONTROL = 0x100001
TH32CS_SNAPTHREAD = 4


class THREADENTRY32(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ThreadID', wt.DWORD),
                ('th32OwnerProcessID', wt.DWORD), ('tpBasePri', ctypes.c_long),
                ('tpDeltaPri', ctypes.c_long), ('dwFlags', wt.DWORD)]


class FILETIME(ctypes.Structure):
    _fields_ = [('lo', wt.DWORD), ('hi', wt.DWORD)]


class SYMBOL_INFO(ctypes.Structure):
    _fields_ = [('SizeOfStruct', wt.ULONG), ('TypeIndex', wt.ULONG), ('Reserved', ctypes.c_uint64 * 2),
                ('Index', wt.ULONG), ('Size', wt.ULONG), ('ModBase', ctypes.c_uint64), ('Flags', wt.ULONG),
                ('Value', ctypes.c_uint64), ('Address', ctypes.c_uint64), ('Register', wt.ULONG),
                ('Scope', wt.ULONG), ('Tag', wt.ULONG), ('NameLen', wt.ULONG), ('MaxNameLen', wt.ULONG),
                ('Name', ctypes.c_char * 256)]


k32.OpenProcess.restype = wt.HANDLE
k32.OpenThread.restype = wt.HANDLE
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE


def find_pid():
    out = subprocess.run(['tasklist', '/fi', 'imagename eq SecretRingsRecomp.exe', '/fo', 'csv', '/nh'],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    sys.exit('SecretRingsRecomp.exe is not running')


def threads(pid):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(te)
    ok = k32.Thread32First(snap, ctypes.byref(te))
    while ok:
        if te.th32OwnerProcessID == pid:
            yield te.th32ThreadID
        ok = k32.Thread32Next(snap, ctypes.byref(te))
    k32.CloseHandle(snap)


def cpu_time(h):
    c, e, kt, ut = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    k32.GetThreadTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut))
    return ((kt.hi << 32) | kt.lo) + ((ut.hi << 32) | ut.lo)


def busiest(pid):
    hs = {t: k32.OpenThread(THREAD_ALL, False, t) for t in threads(pid)}
    t0 = {t: cpu_time(h) for t, h in hs.items() if h}
    time.sleep(1)
    best = max(t0, key=lambda t: cpu_time(hs[t]) - t0[t])
    for h in hs.values():
        if h:
            k32.CloseHandle(h)
    return best


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else 10
    top = int(sys.argv[sys.argv.index('--top') + 1]) if '--top' in sys.argv else 30
    pid = find_pid()
    tid = int(sys.argv[sys.argv.index('--tid') + 1]) if '--tid' in sys.argv else busiest(pid)
    hp = k32.OpenProcess(PROCESS_ALL, False, pid)
    ht = k32.OpenThread(THREAD_ALL, False, tid)
    buf = ctypes.create_string_buffer(1232 + 16)
    ctx = (ctypes.addressof(buf) + 15) & ~15
    counts = collections.Counter()
    end = time.time() + secs
    n = 0
    while time.time() < end:
        if k32.SuspendThread(ht) != 0xFFFFFFFF:
            ctypes.memset(ctx, 0, 1232)
            ctypes.c_uint32.from_address(ctx + 0x30).value = CONTEXT_CONTROL
            if k32.GetThreadContext(ht, ctypes.c_void_p(ctx)):
                counts[ctypes.c_uint64.from_address(ctx + 0xF8).value] += 1
                n += 1
            k32.ResumeThread(ht)
        time.sleep(0.001)
    dbg.SymSetOptions(0x2 | 0x4)   # undecorated names, deferred loads
    if not dbg.SymInitialize(hp, None, True):
        sys.exit(f'SymInitialize failed ({ctypes.get_last_error()})')
    by_fn = collections.Counter()
    sym = SYMBOL_INFO()
    for rip, c in counts.items():
        sym.SizeOfStruct = ctypes.sizeof(SYMBOL_INFO) - 256
        sym.MaxNameLen = 255
        disp = ctypes.c_uint64()
        name = sym.Name.decode() if dbg.SymFromAddr(hp, ctypes.c_uint64(rip), ctypes.byref(disp), ctypes.byref(sym)) else f'?{rip:x}'
        by_fn[name] += c
    print(f'thread {tid}: {n} samples in {secs:.0f} s')
    for name, c in by_fn.most_common(top):
        print(f'{100 * c / n:6.2f}%  {name}')


if __name__ == '__main__':
    main()
