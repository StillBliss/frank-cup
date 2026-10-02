"""Stress test 4: how much does the 2027 board move when the inputs or assumptions move?"""
import json, copy, collections, numpy as np
from scipy.stats import spearmanr
import talent, value27 as V, stress_lib as S

def build(team_ctx=True, **over):
    S.reset()
    for k, v in over.items(): setattr(talent, k, v)
    T, _ = talent.build(); talent.durability(T)
    if team_ctx: talent.team_context(T)
    talent.pedigree(T); talent.fielding(T)
    S.reset()
    return T

def board(T, value='wp_season', **kw):
    pool, meta = V.run(T, **kw)
    vals = {S.key(p): p[value] * (p.get('avail', 1) * p.get('mlb_share', 1) if value == 'cw' else 1) for p in pool}
    order = sorted(vals, key=lambda k: -vals[k])
    mu = np.mean([vals[k] for k in order[:216]])
    return {k: i + 1 for i, k in enumerate(order)}, {k: 100 + 20 * (v - mu) / mu for k, v in vals.items()}, {S.key(p): p['name'] for p in pool}, {S.key(p): p['role'] for p in pool}

V.set_context(2027)
T0 = build()
R0, G0, NM, ROLE = board(T0)
top150 = [k for k in R0 if R0[k] <= 150]; top50 = [k for k in top150 if R0[k] <= 50]

def compare(lab, R, G):
    d = np.array([R.get(k, 999) - R0[k] for k in top150])
    d50 = np.array([abs(R.get(k, 999) - R0[k]) for k in top50])
    rho = spearmanr([R0[k] for k in top150], [R.get(k, 999) for k in top150])[0]
    keep12 = len({k for k in R if R[k] <= 12} & {k for k in R0 if R0[k] <= 12})
    keep50 = len({k for k in R if R[k] <= 50} & set(top50))
    mv = sorted(top150, key=lambda k: R.get(k, 999) - R0[k])
    up = ', '.join(f"{NM[k].split()[-1]} {R0[k]}>{R.get(k, 999)}" for k in mv[:2]); dn = ', '.join(f"{NM[k].split()[-1]} {R0[k]}>{R.get(k, 999)}" for k in mv[-2:])
    print(f"{lab:44s} agree {rho:.3f}  avg move top50 {d50.mean():4.1f}  top150 {np.abs(d).mean():4.1f}  moved 20+: {(np.abs(d) >= 20).sum():3d}  same top 12: {keep12}/12  top 50: {keep50}/50  | {up} | {dn}")
    return dict(rho=float(rho), mv50=float(d50.mean()), mv150=float(np.abs(d).mean()), big=int((np.abs(d) >= 20).sum()), k12=keep12, k50=keep50)

OUT = {}
print('--- the engine (same player projections, different league assumptions)')
def with_(setter, undo, lab, ctx=2027, **kw):
    setter(); V.set_context(ctx); R, G, _, _ = board(T0, **kw); OUT[lab] = compare(lab, R, G); undo(); V.set_context(2027)
def setv(**kv):
    def f():
        for k, v in kv.items(): setattr(V, k, v)
    return f
base = dict(RECENCY=0.85, OPP_FROM=2014, WIN_AT=10.5, G_WEEK=6.0, SP_WEEK=1.25, RP_WEEK=2.5, RP_IP_WEEK=3.5)
u = setv(**base)
with_(setv(RECENCY=1.0), u, 'all past seasons count the same')
with_(setv(RECENCY=0.7), u, 'recent seasons count much more')
with_(setv(OPP_FROM=2021), u, 'opponents from 2021 on only')
with_(setv(OPP_FROM=2024), u, 'opponents from 2024 on only')
with_(lambda: None, u, 'no 2027 rule adjustment (2026 volumes)', ctx=2026)
with_(setv(G_WEEK=5.5), u, 'hitters play 5.5 games a week, not 6')
with_(setv(SP_WEEK=1.15), u, 'starters 1.15 starts a week, not 1.25')
with_(setv(SP_WEEK=1.4), u, 'starters 1.4 starts a week')
with_(setv(RP_WEEK=2.0, RP_IP_WEEK=3.0), u, 'relievers 2 outings a week, not 2.5')
with_(setv(RP_WEEK=3.0, RP_IP_WEEK=4.0), u, 'relievers 3 outings a week')
st = dict(V.STEP)
def step(f):
    def g():
        for k in V.STEP: V.STEP[k] = st[k] * f
    return g
with_(step(2.0), step(1.0), 'softer category margins (x2)')
with_(step(0.5), step(1.0), 'sharper category margins (x0.5)')
pb = copy.deepcopy(V.PBANDS)
def bands(sp, rp):
    def g(): V.PBANDS[12] = {'SP': sp, 'RP': rp}
    return g
with_(bands((90, 115), (18, 34)), bands(*pb[12].values()), 'fewer pitchers rostered (deeper waiver wire)')
with_(bands((120, 145), (32, 48)), bands(*pb[12].values()), 'more pitchers rostered (thinner waiver wire)')
hs = dict(V.HSLOTS)
def hsl(n):
    def g(): V.HSLOTS['Util'] = n
    return g
with_(hsl(3), hsl(2), 'one extra hitter rostered per team')
V.set_context(2027)
R, G, _, _ = board(T0, value='cw'); OUT['cats'] = compare('rank by categories won, not matchups won', R, G)

print('--- the player projections')
def reb(lab, team_ctx=True, **over):
    T = build(team_ctx=team_ctx, **over); R, G, _, _ = board(T); OUT[lab] = compare(lab, R, G)
reb('durability refit (candidate)', DUR_V2=True)
reb('no team context', team_ctx=False)
reb('no prospect pedigree', PEDIGREE_ON=False, PIPE_EXCLUDE={'current'} | {f'preseason_{y}' for y in range(2020, 2030)})
reb('no age curve', AGE_ON=False)
reb('season weights 6/3/1 instead of 5/4/3', SEASONS={2026: 6, 2025: 3, 2024: 1})
reb('season weights 1/1/1', SEASONS={2026: 1, 2025: 1, 2024: 1}, PRIOR_PA=500, PRIOR_BF=425)
reb('lighter pull to average (1200/1000)', PRIOR_PA=1200, PRIOR_BF=1000)
reb('heavier pull to average (3000/2500)', PRIOR_PA=3000, PRIOR_BF=2500)
reb('minor league stats count half as much', MILB_DISC=0.15, MILB_DISC_P=0.2)
reb('minor league stats count double', MILB_DISC=0.6, MILB_DISC_P=0.8)

print('--- luck of which weeks we happened to play (bootstrap, 20 redraws of the 2,508 opponent weeks)')
rng = np.random.default_rng(7)
w0 = V.wts.copy(); ranks = collections.defaultdict(list); grades = collections.defaultdict(list)
for b in range(20):
    idx = rng.choice(len(w0), len(w0), p=w0); w = np.bincount(idx, minlength=len(w0)).astype(float); V.wts = w / w.sum()
    R, G, _, _ = board(T0)
    for k in top150: ranks[k].append(R.get(k, 999)); grades[k].append(G.get(k, 0))
V.wts = w0
sd = {k: float(np.std(ranks[k])) for k in top150}; gsd = {k: float(np.std(grades[k])) for k in top150}
for a, b in ((1, 12), (13, 50), (51, 100), (101, 150)):
    ks = [k for k in top150 if a <= R0[k] <= b]
    print(f"   ranks {a:3d}-{b:3d}: typical wobble +/- {np.median([sd[k] for k in ks]):.1f} spots, grade +/- {np.median([gsd[k] for k in ks]):.1f}; worst {max(sd[k] for k in ks):.1f} ({NM[max(ks, key=lambda k: sd[k])]})")
OUT['boot'] = {f'{a}-{b}': float(np.median([sd[k] for k in top150 if a <= R0[k] <= b])) for a, b in ((1, 12), (13, 50), (51, 100), (101, 150))}
json.dump(OUT, open('stress4.json', 'w'))
