"""Stress test 3: which parts of the formula earn their keep?  Same October-board test, one piece changed at a time,
scored on two seasons (2025 and 2026) by real value captured and by rank agreement with what happened."""
import json, numpy as np
from scipy.stats import spearmanr
import talent, stress_lib as S

CACHE = {}; LAST = {}
def truth(target):
    if target not in CACHE:
        rev, _ = S.actual(target)
        last, _ = S.actual(target - 1)
        CACHE[target] = ({S.key(p): max(0.0, 100 * p['wp']) for p in rev}, S.draft(target), {S.nkey(p): S.key(p) for p in rev})
        LAST[target] = [S.key(p) for p in sorted(last, key=lambda p: -p['wp'])]
    return CACHE[target]

def evaluate(target, post=None, **over):
    act, dr, rev_names = truth(target)
    pool, meta, T = S.project(target, post=post, **over)
    names = {S.nkey(p): S.key(p) for p in sorted(pool, key=lambda p: p['wp_season'])}
    for k, v in rev_names.items(): names.setdefault(k, v)
    model = [S.key(p) for p in sorted(pool, key=lambda p: -p['wp_season'])]
    rank = {k: i for i, k in enumerate(model)}
    out = {}
    for nh, np_, lab in ((100, 90, 'full'), (50, 40, 'half'), (20, 15, 'early')):
        h = [k for k in model if k[0] == 'H'][:nh]; p = [k for k in model if k[0] == 'P'][:np_]
        out[lab] = sum(act.get(k, 0) for k in h + p)
    drafted = {names[k]: v[0] for k, v in dr.items() if k in names}
    ks = sorted(set(drafted) | set(LAST[target][:300]))            # a fixed group known before the season: no hindsight in who is scored
    a = [act.get(k, 0) for k in ks]
    out['corr'] = spearmanr([-rank.get(k, 5000) for k in ks], a)[0]
    val = {S.key(p): 100 * p['wp_season'] for p in pool}
    out['pear'] = float(np.corrcoef([max(0, val.get(k, 0)) for k in ks], a)[0, 1])
    lr = {k: i for i, k in enumerate(LAST[target])}
    out['corr_league'] = spearmanr([-drafted.get(k, 400) for k in ks], a)[0]
    out['corr_last'] = spearmanr([-lr.get(k, 5000) for k in ks], a)[0]
    out['n'] = len(ks)
    return out

def no_dur(T):
    for p in T.values(): p['avail'] = 1.0
def no_share(T):
    for p in T.values(): p['mlb_share'] = 1.0 if p['mlb_share'] >= 0.7 else p['mlb_share']

V2 = dict(DUR_V2=True)
variants = [
    ('what we have now', None, {}),
    ('+ durability refit', None, V2),
    ('refit, but no injury adjustment at all', no_dur, V2),
    ('refit, no carry-over for finishing on the IL', None, dict(DUR_V2=True, CARRY_ON=False)),
    ('refit, no age curve', None, dict(DUR_V2=True, AGE_ON=False)),
    ('refit, no prospect pedigree', None, dict(DUR_V2=True, PEDIGREE_ON=False, PIPE_EXCLUDE={'current'} | {f'preseason_{y}' for y in range(2020, 2030)})),
    ('refit, no minor league stats', None, dict(DUR_V2=True, MILB_W={})),
    ('refit, lighter pull to average (1200/1000)', None, dict(DUR_V2=True, PRIOR_PA=1200, PRIOR_BF=1000)),
    ('refit, heavier pull to average (3000/2500)', None, dict(DUR_V2=True, PRIOR_PA=3000, PRIOR_BF=2500)),
]
res = {}
print(f"{'':46s} {'value captured (2025 + 2026)':>30s}   rank agreement")
print(f"{'':46s} {'full':>8s} {'top half':>9s} {'early':>7s}   {'2025':>6s} {'2026':>6s}")
for lab, post, over in variants:
    r = {t: evaluate(t, post=post, **over) for t in (2025, 2026)}
    res[lab] = r
    print(f"{lab:46s} {r[2025]['full'] + r[2026]['full']:8.1f} {r[2025]['half'] + r[2026]['half']:9.1f} {r[2025]['early'] + r[2026]['early']:7.1f}   {r[2025]['corr']:6.3f} {r[2026]['corr']:6.3f}   value corr {r[2025]['pear']:.3f} {r[2026]['pear']:.3f}")
r = res['what we have now']
print('same group, league draft order:', round(r[2025]['corr_league'], 3), round(r[2026]['corr_league'], 3), ' last year rank:', round(r[2025]['corr_last'], 3), round(r[2026]['corr_last'], 3), ' players:', r[2025]['n'], r[2026]['n'])
json.dump(res, open('stress3.json', 'w'))
