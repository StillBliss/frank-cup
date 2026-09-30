import champ as C, numpy as np, itertools
K = C.K
names = C.TEAM['Benny']['SP']
for n in names:
    u = C.line('P', n, C.fa_sp); g = dict(zip(K, u))
    print(f"{n:15s} IP {g['IP']:.1f}  ERA {9*g['ER']/g['IP']:.2f}  WHIP {g['BR']/g['IP']:.2f}  K {g['K']:.1f}  QS% {100*g['QS']:.0f}")
full = C.L['Benny']
out = []
for k in range(0, 6):
    for combo in itertools.combinations(range(5), k):
        C.L['Benny'] = (full[0], [full[1][i] for i in combo], full[2])
        C.rng = np.random.default_rng(5)
        res, flip, mg, n = C.score(6000)
        out.append((res['Benny'] / n, [names[i] for i in combo], {c: round(100 * flip[c][0] / n) for c in ('ERA', 'QS', 'L', 'W', 'WHIP', 'K/BB')}))
out.sort(key=lambda x: -x[0])
for w, combo, fc in out[:8]: print(round(100 * w, 1), combo, fc)
print('...')
for w, combo, fc in out:
    if len(combo) in (0, 5): print(round(100 * w, 1), combo, fc)
