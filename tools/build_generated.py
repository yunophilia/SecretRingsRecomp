"""Regenerate the recompiled C++ sources.

  python tools/build_generated.py [--reanalyze] [--dsy PATH]

Steps per code set (tools/regions.py): function analysis (cached in out/), signature
matching, override scan of runtime/ (functions the runtime replaces), code generation
(files are only rewritten when their content changes).

Code sets:
  base  the USA/Japan main.dol (required)   -> generated/        out/functions.json
  eu    the European main.dol (optional)    -> generated/eu/     out/eu/functions.json
Both are recompiled together: the European functions that match base ones share their
code (in generated/), and only the European build's own functions and dispatch table
go to generated/eu/.
Each main.dol (with its SONICRINGS.sel) is taken from the installed game data
(game/extracted/DATA) or from game/inputs/<game ID>/ (sys/main.dol,
files/SONICRINGS.sel), which `srr_install --build-inputs <image>` writes for the other
releases. Without the European main.dol the build only runs the USA and Japanese
releases.

SDK function names only matter for tools/xref.py and reports; the generated code is
the same without them. They come from tools/sdk_names.txt (recorded from a match
against Dolphin's signature database), or, to rematch, from a totaldb.dsy given with
--dsy or the SRR_TOTALDB environment variable. Dolphin is not needed. The European
build gets the names of the base build's matching functions.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, 'tools')
GEN = os.path.join(ROOT, 'generated')
OUT = os.path.join(ROOT, 'out')

sys.path.insert(0, TOOLS)
from dol import Dol                                                    # noqa: E402
from regions import CODE_SETS, dol_sha1, match_functions             # noqa: E402

SETS = {   # code set -> (functions.json, generated dir)
    'base': (os.path.join(OUT, 'functions.json'), GEN),
    'eu': (os.path.join(OUT, 'eu', 'functions.json'), os.path.join(GEN, 'eu')),
}


def run(*args):
    print('>', ' '.join(args), flush=True)
    subprocess.check_call([sys.executable, *args], cwd=ROOT)


def scan_overrides():
    pat = re.compile(r'PPC_FUNC\(\s*fn_([0-9A-Fa-f]{8})\s*\)')
    found = set()
    for d, _, files in os.walk(os.path.join(ROOT, 'runtime')):
        for f in files:
            if f.endswith(('.cpp', '.h')):
                txt = open(os.path.join(d, f), encoding='utf-8', errors='ignore').read()
                found.update(int(m, 16) for m in pat.findall(txt))
    return sorted(found)


def find_dsy():
    if '--dsy' in sys.argv:
        return sys.argv[sys.argv.index('--dsy') + 1]
    dsy = os.environ.get('SRR_TOTALDB')
    return dsy if dsy and os.path.exists(dsy) else None


def find_inputs():
    """code set -> (main.dol, SONICRINGS.sel) from the installed data and game/inputs/."""
    found = {}
    dirs = [os.path.join(ROOT, 'game', 'extracted', 'DATA')] + sorted(glob.glob(os.path.join(ROOT, 'game', 'inputs', '*')))
    for d in dirs:
        dol = os.path.join(d, 'sys', 'main.dol')
        sel = os.path.join(d, 'files', 'SONICRINGS.sel')
        if not (os.path.exists(dol) and os.path.exists(sel)):
            continue
        cs = CODE_SETS.get(dol_sha1(dol))
        if not cs:
            print(f'{dol}: unknown main.dol, ignored')
        elif cs[0] not in found:
            found[cs[0]] = (dol, sel)
    return found


def analyze(cs, dol, sel, names):
    """Function list of a code set, reanalyzed when its main.dol changes."""
    funcs = SETS[cs][0]
    stamp = funcs + '.dol'
    sha = dol_sha1(dol)
    cached = os.path.exists(funcs) and os.path.exists(stamp) and open(stamp).read().strip() == sha
    if cs == 'base' and os.path.exists(funcs) and not os.path.exists(stamp):
        cached = True   # analysis from before code sets were checked
    if '--reanalyze' in sys.argv or not cached:
        os.makedirs(os.path.dirname(funcs), exist_ok=True)
        run(os.path.join(TOOLS, 'analyze.py'), dol, sel, funcs)
        if names:
            run(os.path.join(TOOLS, 'sigdb.py'), dol, funcs, names)
    with open(stamp, 'w') as fp:
        fp.write(sha + '\n')
    return json.load(open(funcs))


def main():
    os.makedirs(OUT, exist_ok=True)
    inputs = find_inputs()
    if 'base' not in inputs:
        sys.exit('the USA or Japanese main.dol is needed: install the game data (out/srr_install <image>) '
                 'or put a USA/Japan release\'s inputs in game/inputs/ (srr_install --build-inputs <image>)')
    ovr = scan_overrides()
    ovr_file = os.path.join(OUT, 'overrides.txt')
    with open(ovr_file, 'w') as fp:
        fp.write('\n'.join(f'{a:08X}' for a in ovr))
    print(f'{len(ovr)} runtime overrides')

    # SDK names: rematch with a given totaldb.dsy, else the recorded names
    base_dol, base_sel = inputs['base']
    base_funcs = analyze('base', base_dol, base_sel, find_dsy() or os.path.join(TOOLS, 'sdk_names.txt'))

    eu_gen = SETS['eu'][1]
    if 'eu' not in inputs:
        if os.path.isdir(eu_gen):
            shutil.rmtree(eu_gen)
        print('no European main.dol: the build supports the USA and Japanese releases only')
        run(os.path.join(TOOLS, 'recomp.py'), base_dol, SETS['base'][0], GEN, ovr_file)
        return
    eu_dol, eu_sel = inputs['eu']
    eu_path = SETS['eu'][0]
    eu_funcs = analyze('eu', eu_dol, eu_sel, None)
    match = match_functions(Dol(base_dol), base_funcs, Dol(eu_dol), eu_funcs)
    print(f'European build: {len(match)} of {len(eu_funcs)} functions match the base build')
    names = {f['start']: f['name'] for f in base_funcs if f.get('name')}
    rev = {v: k for k, v in match.items()}
    for f in eu_funcs:
        if not f.get('name') and rev.get(f['start']) in names:
            f['name'] = names[rev[f['start']]]
    with open(eu_path, 'w') as fp:
        json.dump(eu_funcs, fp)
    # one recompilation of both builds: matched functions share their code
    run(os.path.join(TOOLS, 'recomp.py'), base_dol, SETS['base'][0], GEN, ovr_file, '--eu', eu_dol, eu_path, eu_gen)


if __name__ == '__main__':
    main()
