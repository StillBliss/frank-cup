"""Stress test 1: does the board predict the next season?  Pretend it is October, build the board,
then score it against what really happened. Benchmarks: the league's own draft the following March
(five months more news, plus Yahoo's list in front of everyone) and 'just rank by last year'."""
import json, collections, sys
import numpy as np
from scipy.stats import spearmanr
import stress_lib as S

OUT = {}
for target in (2026, 2025):
    print(f'\n================ target season {target}')
    pool, meta, T = S.project(target)
    rev, _ = S.actual(target)
    last, _ = S.actual(target - 1)
    act = {S.key(p): max(0.0, 100 * p['wp']) for p in rev}           # value to a manager: you can always drop a negative
    raw = {S.key(p): 100 * p['wp'] for p in rev}
    names = {S.nkey(p): S.key(p) for p in sorted(pool, key=lambda p: p['wp_season'])}   # best player wins a name clash
    for p in rev: names.setdefault(S.nkey(p), S.key(p))
    dr = S.draft(target)
    miss = [v[3] for k, v in dr.items() if k not in names]
    print('drafted players not matched to MLB data:', len(miss), miss[:12])

    model = [S.key(p) for p in sorted(pool, key=lambda p: -p['wp_season'])]
    lasty = [S.key(p) for p in sorted(last, key=lambda p: -p['wp'])]
    league = [names[k] for k, v in sorted(dr.items(), key=lambda kv: kv[1][0]) if k in names]
    hind = [k for k, _ in sorted(act.items(), key=lambda kv: -kv[1])]
    lists = {'model (October)': model, 'league draft (March)': league, 'last year rank': lasty, 'perfect hindsight': hind}

    def take(lst, nh, np_):
        h = [k for k in lst if k[0] == 'H'][:nh]; p = [k for k in lst if k[0] == 'P'][:np_]
        return h, p
    res = {}
    for nh, np_, lab in ((100, 90, 'full rosters (100 H + 90 P)'), (50, 40, 'top half (50 H + 40 P)'), (20, 15, 'early rounds (20 H + 15 P)')):
        print(f'-- total real value captured, {lab}')
        for name, lst in lists.items():
            h, p = take(lst, nh, np_)
            vh, vp = sum(act.get(k, 0) for k in h), sum(act.get(k, 0) for k in p)
            res[(lab, name)] = (vh, vp)
            print(f'   {name:22s} hitters {vh:6.1f}  pitchers {vp:6.1f}  total {vh + vp:6.1f}')
    # rank agreement with what happened, on the players the league actually drafted (non keepers)
    rank_m = {k: i for i, k in enumerate(model)}; rank_l = {}
    for k, v in dr.items():
        if k in names: rank_l[names[k]] = v
    common = [k for k in rank_l if k in rank_m and not rank_l[k][2]]
    for side in ('H', 'P', 'all'):
        ks = [k for k in common if side == 'all' or k[0] == side]
        a = [act.get(k, 0) for k in ks]
        rm = spearmanr([-rank_m[k] for k in ks], a)[0]; rl = spearmanr([-rank_l[k][0] for k in ks], a)[0]
        print(f'   rank vs real value, drafted non-keepers {side:3s} n={len(ks):3d}:  model {rm:.3f}   league pick order {rl:.3f}')
    # disagreements: model's rank among drafted players vs the pick they went
    order_m = sorted(common, key=lambda k: rank_m[k]); pos_m = {k: i for i, k in enumerate(order_m)}
    order_l = sorted(common, key=lambda k: rank_l[k][0]); pos_l = {k: i for i, k in enumerate(order_l)}
    order_a = sorted(common, key=lambda k: -raw.get(k, -9)); pos_a = {k: i for i, k in enumerate(order_a)}
    gaps = sorted(common, key=lambda k: pos_m[k] - pos_l[k])
    nm = {S.key(p): p['name'] for p in pool}
    def show(ks, lab):
        right = 0
        print(f'   {lab}')
        for k in ks:
            closer = abs(pos_m[k] - pos_a[k]) < abs(pos_l[k] - pos_a[k]); right += closer
            print(f'      {nm[k][:22]:22s} model {pos_m[k] + 1:3d}  league {pos_l[k] + 1:3d}  actual {pos_a[k] + 1:3d}  {"MODEL" if closer else "league"}')
        return right
    r1 = show(gaps[:15], 'model liked far more than the league did'); r2 = show(gaps[-15:], 'model liked far less than the league did')
    print(f'   model closer on {r1}/15 it liked more, {r2}/15 it liked less')
    allc = sum(abs(pos_m[k] - pos_a[k]) < abs(pos_l[k] - pos_a[k]) for k in common if abs(pos_m[k] - pos_l[k]) >= 25)
    alln = sum(1 for k in common if abs(pos_m[k] - pos_l[k]) >= 25)
    print(f'   all big disagreements (25+ spots): model closer on {allc} of {alln}')
    OUT[target] = {'res': {f'{a}|{b}': v for (a, b), v in res.items()}, 'big': (allc, alln)}
json.dump(OUT, open('stress1.json', 'w'))
