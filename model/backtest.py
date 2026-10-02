"""Pretend it's October 2025: project 2026 from 2023-2025 only, then compare to what really happened in 2026.
Scores each variant by how well projected per-game win value matches actual 2026 per-game win value."""
import datetime as dt, pickle, numpy as np, talent, value27 as V
from scipy.stats import spearmanr
_, meta = pickle.load(open('v27.pkl', 'rb'))
REPL = meta['repl']; qb = V.qs_model()
BASE = {r: V.score(V.swap(REPL[r], REPL[r])) for r in REPL}

def value(T):
    out = {}
    for key, p in T.items():
        line = V.weekly(p, qb)
        cw, wp, per = V.score(V.swap(line, REPL[p['role']]))
        out[key] = (wp - BASE[p['role']][1], p['role'])
    return out

def setup(seasons, milb, prior_pa, prior_bf, age_on, age_date, ped=False):
    talent.SEASONS = seasons; talent.MILB_W = milb; talent.PRIOR_PA = prior_pa; talent.PRIOR_BF = prior_bf
    talent.AGE_ON = age_on; talent.AGE_DATE = age_date; talent.PEDIGREE_ON = ped
    T, _ = talent.build(); return T

# what actually happened in 2026 (no regression, no aging)
T26 = setup({2026: 1}, {}, 1, 1, False, dt.date(2026, 7, 1))
keep = {k for k, p in T26.items() if (p['role'] == 'H' and p['mlb_pa'] >= 350) or (p['role'] == 'SP' and p['mlb_bf'] >= 350) or (p['role'] == 'RP' and p['mlb_bf'] >= 180)}
actual = value(T26)
print('players scored on:', len(keep))

def test(label, seasons, milb={2025: 5}, prior_pa=1200, prior_bf=1000, age_on=True):
    T = setup(seasons, milb, prior_pa, prior_bf, age_on, dt.date(2026, 7, 1))
    proj = value(T)
    res = []
    for role in ('H', 'SP', 'RP', 'all'):
        ks = [k for k in keep if k in proj and (role == 'all' or actual[k][1] == role)]
        a = np.array([actual[k][0] for k in ks]); b = np.array([proj[k][0] for k in ks])
        res.append((spearmanr(a, b)[0], float(np.sqrt(np.mean((100 * a - 100 * b) ** 2))), len(ks)))
    print(f"{label:34s} " + '  '.join(f"{r}: r={x[0]:.3f} err={x[1]:.2f}" for r, x in zip(('H', 'SP', 'RP', 'all'), res)))
    return res

print('--- naive baselines')
test('last year only (2025, raw)', {2025: 1}, {}, 1, 1, False)
test('3-year flat average, raw', {2025: 1, 2024: 1, 2023: 1}, {}, 1, 1, False)
print('--- weights (regressed, aged, minors)')
for w in [(5, 4, 3), (6, 3, 1), (4, 3, 3), (3, 2, 1), (8, 4, 2), (5, 3, 2), (1, 0, 0)]:
    test(f'weights {w}', {2025: w[0], 2024: w[1], 2023: w[2]})
print('--- how hard to pull toward average (weights 5/4/3)')
for ppa, pbf in [(300, 250), (600, 500), (1200, 1000), (2000, 1700), (3000, 2500)]:
    test(f'prior {ppa} PA / {pbf} BF', {2025: 5, 2024: 4, 2023: 3}, prior_pa=ppa, prior_bf=pbf)
print('--- switches')
test('no age adjustment', {2025: 5, 2024: 4, 2023: 3}, age_on=False)
test('no minor league stats', {2025: 5, 2024: 4, 2023: 3}, milb={})
