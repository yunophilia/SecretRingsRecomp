"""Generate a random-input soak script for long stability runs.

  python tools/gen_soak.py out/soak.txt [--seconds 900] [--seed N]

The script first replays tools/scripts/stage1.txt up to the stage start (Lost Prologue,
paragraph 1), then mixes steering, jumps, homing attacks (thrusts), brakes, backtracking,
pauses, menu confirmations and short D-pad bursts. Run it with:

  powershell -ExecutionPolicy Bypass -File tools/run_test.ps1 -Seconds 900 \\
      -GameArgs "--nobox --skip-launcher --input-script <abs path> --shots 1800 --shots-start 1800"

then look for [E] lines in out/SecretRingsRecomp.log and review the screenshots.
"""
import argparse
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--seconds', type=float, default=900)
    ap.add_argument('--seed', type=int, default=1)
    a = ap.parse_args()
    head = [l for l in open(os.path.join(HERE, 'scripts', 'stage1.txt')).read().split('\n')
            if l.strip() and not l.startswith('#') and float(l.split()[0]) < 60]
    rnd = random.Random(a.seed)
    t, lines = 62.0, []
    while t < a.seconds - 10:
        r = rnd.random()
        if r < 0.35:
            lines.append(f'{t:.1f} {rnd.uniform(0.5, 3):.1f} LX={rnd.uniform(-1, 1):.2f}')
        elif r < 0.55:
            lines.append(f'{t:.1f} 0.2 A')
        elif r < 0.65:   # jump, then thrust in the air (homing attack)
            lines += [f'{t:.1f} 0.2 A', f'{t + 0.3:.1f} 0.15 X']
            t += 0.5
        elif r < 0.72:
            lines.append(f'{t:.1f} {rnd.uniform(0.3, 1.5):.1f} B')
        elif r < 0.76:   # backtrack
            lines.append(f'{t:.1f} {rnd.uniform(0.5, 2):.1f} LY=-1.0')
        elif r < 0.84:   # D-pad bursts + confirm: menus, results, mission select
            d, n = rnd.choice(['RIGHT', 'LEFT', 'UP', 'DOWN']), rnd.randint(1, 3)
            lines += [f'{t + 0.4 * k:.1f} 0.15 {d}' for k in range(n)]
            lines.append(f'{t + 0.4 * n + 0.3:.1f} 0.2 A')
            t += 0.4 * n + 0.4
        elif r < 0.86:   # pause and resume
            lines += [f'{t:.1f} 0.2 START', f'{t + 1.5:.1f} 0.2 START']
            t += 1.8
        else:
            lines.append(f'{t:.1f} 0.15 X')
        t += rnd.uniform(0.3, 1.2)
    open(a.out, 'w').write('\n'.join(head + lines) + '\n')
    print(f'{len(lines)} events, {a.seconds:.0f} s')


if __name__ == '__main__':
    main()
