"""Candidate position vectors: float triplets that move steadily across dumps p0..p4."""
import numpy as np, sys
D = 'out/dumps/'
names = sys.argv[1:] or ['p0', 'p1', 'p2', 'p3', 'p4']
for region, base in (('mem1', 0x80000000), ('mem2', 0x90000000)):
    a = [np.frombuffer(open(D + n + '.' + region, 'rb').read(), dtype='>f4').astype(np.float64) for n in names]
    A = np.stack(a)                       # dumps x words
    fin = np.all(np.isfinite(A), axis=0) & np.all(np.abs(A) < 1e5, axis=0)
    d01 = np.abs(A[1] - A[0])
    ok = fin & (d01 > 3) & (d01 < 400)
    # all consecutive dumps differ
    for i in range(1, len(names)):
        ok &= np.abs(A[i] - A[i - 1]) > 0.5
    idx = np.nonzero(ok)[0]
    # keep words whose neighbours (triplet) are also finite
    hits = []
    for i in idx:
        if i + 2 < A.shape[1] and fin[i:i + 3].all():
            hits.append(i)
    print(region, len(hits))
    for i in hits[:80]:
        print(hex(base + 4 * i), ' '.join(f'{v:10.2f}' for v in A[:, i]), '|', ' '.join(f'{v:10.2f}' for v in A[:, i + 1]), '|', ' '.join(f'{v:10.2f}' for v in A[:, i + 2]))
