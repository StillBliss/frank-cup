"""
Hindsight 2026 draft for Benny (team 1).

- Every other manager's picks (and all keepers) stay exactly as they happened.
- Benny keeps his 3 keepers (Rice, Carroll, Kirby) and redoes his 21 real picks.
- A player is available to Benny at a pick only if no one else had taken him yet.
- Draftable pool: everyone drafted, plus Yahoo's preseason top 300 hitters and 300 pitchers.
- Value: 2026 season-total win value (missed time counts), from the season board.
- Roster: 10 or 11 hitters, 3 or 4 RP, rest SP (24 total). Objective counts the
  best legal 10-man hitting lineup (C,1B,2B,3B,SS,OF,OF,OF,Util,Util) fully, bench bats
  at 15%, and every pitcher fully (daily lineups use nearly every rostered arm).
"""
import json, glob, sys, numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds
sys.path.insert(0, '/home/claude/frank-cup/scripts')
import sources
from model import norm

RAW = '/home/claude/frank-cup/raw/2026'
RES = '/home/claude/research/research_out'
ME = '.t.1'
SLOTS = ['C', '1B', '2B', '3B', 'SS', 'OF', 'OF', 'OF', 'Util', 'Util']
BENCH_W = 0.15

rank = json.load(open('rank.json'))
val = {}
for p in rank['season']:
    val[('H' if p['role'] == 'H' else 'P', norm(p['n']))] = (p['wp'], p['role'], p)
floor = {r: min(p['wp'] for p in rank['season'] if p['role'] == r) for r in ('H', 'SP', 'RP')}

def flat(block):
    out = {}
    for part in block:
        if isinstance(part, dict): out.update(part)
    return out

pool = {}   # key -> dict
d = json.load(open(f'{RAW}/draft_results.json'))['fantasy_content']['league'][1]['draft_results']
my_picks, keepers = [], []
for i in range(d['count']):
    x = d[str(i)]['draft_result']
    info = flat(x['0']['players']['0']['player'][0])
    side = 'H' if info.get('position_type') == 'B' else 'P'
    name = info['name']['full']
    el = {e['position'] for e in info.get('eligible_positions', [])} if isinstance(info.get('eligible_positions'), list) else set(info.get('display_position', '').split(','))
    kept = bool(info.get('is_keeper', {}).get('kept'))
    k = (side, norm(name))
    mine = x['team_key'].endswith(ME)
    pool[k] = dict(name=name, side=side, el=el, pos=info.get('display_position'), taken=x['pick'],
                   by_me=mine, keeper=kept, tm=info.get('editorial_team_abbr'))
    if mine and kept: keepers.append(k)
    elif mine: my_picks.append(x['pick'])
for side, pre in (('H', 'preseason_B'), ('P', 'preseason_P')):
    for f in sorted(glob.glob(f'{RES}/{pre}_*.json')):
        for p in sources._players(json.load(open(f))):
            k = (side, norm(p['n']))
            if k not in pool:
                pool[k] = dict(name=p['n'], side=side, el=set((p['pos'] or '').split(',')), pos=p['pos'],
                               taken=10**6, by_me=False, keeper=False, tm=p['tm'])
my_picks.sort()
NP = len(my_picks)

rows = []
for k, p in pool.items():
    v = val.get(k)
    if v: wp, role = v[0], v[1]
    else:
        role = 'H' if p['side'] == 'H' else ('SP' if 'SP' in p['el'] else 'RP')
        wp = floor[role]
    el = set()
    for e in p['el']:
        e = e.strip()
        if e in ('LF', 'CF', 'RF'): e = 'OF'
        if e: el.add(e)
    if p['side'] == 'H': el.add('Util')
    # how many of my free picks come before someone else took him
    if p['by_me'] and not p['keeper']:
        L = sum(1 for q in my_picks if q <= p['taken'])   # if I pass on him there, assume he's gone right after
    elif p['taken'] >= 10**6: L = NP
    elif p['keeper']: L = 0
    else: L = sum(1 for q in my_picks if q < p['taken'])
    rows.append(dict(key=k, name=p['name'], role=role, wp=wp, el=el, L=L, keeper=k in keepers,
                     by_me=p['by_me'], taken=p['taken'], pos=p['pos'], tm=p['tm']))
rows = [r for r in rows if r['keeper'] or r['L'] > 0]
n = len(rows)
hit = [i for i, r in enumerate(rows) if r['role'] == 'H']
yv = [(i, s) for i in hit for s in range(len(SLOTS)) if SLOTS[s] in rows[i]['el']]
nv = n + len(yv)


def solve(force=None):
    c = np.zeros(nv)
    for i, r in enumerate(rows):
        c[i] = -(r['wp'] * (BENCH_W if r['role'] == 'H' else 1.0))
    for t, (i, s) in enumerate(yv):
        c[n + t] = -(rows[i]['wp'] * (1 - BENCH_W))
    A, lo, hi = [], [], []
    def add(coef, l, h):
        a = np.zeros(nv)
        for j, v in coef: a[j] = v
        A.append(a); lo.append(l); hi.append(h)
    # 24 players, keepers fixed
    add([(i, 1) for i in range(n)], 24, 24)
    for i, r in enumerate(rows):
        if r['keeper']: add([(i, 1)], 1, 1)
    # Hall's condition on free picks (prefix structure)
    for k in range(1, NP + 1) if force is None else []:
        add([(i, 1) for i, r in enumerate(rows) if not r['keeper'] and r['L'] <= k], 0, k)
    # roster shape
    if force is None:   # your real draft is scored as drafted, whatever its shape
        add([(i, 1) for i in hit], 10, 11)
        add([(i, 1) for i, r in enumerate(rows) if r['role'] == 'RP'], 3, 4)
    # lineup slots
    for s in range(len(SLOTS)):
        add([(n + t, 1) for t, (i, ss) in enumerate(yv) if ss == s], 1, 1)
    by_i = {}
    for t, (i, s) in enumerate(yv): by_i.setdefault(i, []).append(n + t)
    for i, ts in by_i.items():
        add([(i, -1)] + [(t, 1) for t in ts], -np.inf, 0)
    if force is not None:
        for i, r in enumerate(rows):
            add([(i, 1)], 1 if r['key'] in force else 0, 1 if r['key'] in force else 0)
    res = milp(c, constraints=LinearConstraint(np.array(A), lo, hi), integrality=np.ones(nv), bounds=Bounds(0, 1))
    z = res.x[:n] > 0.5
    starters = {yv[t][0] for t in range(len(yv)) if res.x[n + t] > 0.5}
    return -res.fun, [i for i in range(n) if z[i]], starters


def order(chosen):
    """put the chosen (non-keeper) players on my actual picks: best available first,
    as long as everyone left can still be taken before someone else grabs him"""
    left = [i for i in chosen if not rows[i]['keeper']]
    def ok(rest, k):
        for j, i in enumerate(sorted(rest, key=lambda i: rows[i]['L'])):
            if rows[i]['L'] <= k + j: return False
        return True
    out = []
    for k, pick in enumerate(my_picks):
        for i in sorted([i for i in left if rows[i]['L'] > k], key=lambda i: -rows[i]['wp']):
            rest = [x for x in left if x != i]
            if ok(rest, k + 1):
                left.remove(i); out.append((pick, i)); break
    return out


best, chosen, st = solve()
actual_keys = {r['key'] for r in rows if r['by_me']}
act, act_chosen, act_st = solve(force=actual_keys)
seq = order(chosen)
out = {'best': best, 'actual': act,
       'picks': [dict(pick=p, rnd=(p - 1) // 10 + 1, name=rows[i]['name'], role=rows[i]['role'], pos=rows[i]['pos'],
                      tm=rows[i]['tm'], wp=rows[i]['wp'], start=i in st,
                      went=(None if rows[i]['taken'] >= 10**6 else rows[i]['taken'])) for p, i in seq],
       'keepers': [dict(name=rows[i]['name'], role=rows[i]['role'], wp=rows[i]['wp']) for i in chosen if rows[i]['keeper']]}
actual_by_pick = {}
dd = json.load(open(f'{RAW}/draft_results.json'))['fantasy_content']['league'][1]['draft_results']
for i in range(dd['count']):
    x = dd[str(i)]['draft_result']
    if x['team_key'].endswith(ME):
        info = flat(x['0']['players']['0']['player'][0]); side = 'H' if info.get('position_type') == 'B' else 'P'
        v = val.get((side, norm(info['name']['full'])))
        actual_by_pick[x['pick']] = (info['name']['full'], v[0] if v else None)
for p in out['picks']:
    p['actual'], p['actual_wp'] = actual_by_pick.get(p['pick'], (None, None))
json.dump(out, open('hindsight.json', 'w'), indent=1, default=float)
print('lineup value  hindsight', round(best, 1), ' actual', round(act, 1))
for p in out['picks']:
    print(f"{p['pick']:4d} R{p['rnd']:2d} {p['name'][:24]:24s} {p['role']:2s} {p['wp']:6.2f} {'*' if p['start'] else ' '} went {p['went']}   | actual {p['actual']} {p['actual_wp']}")
print('keepers', [(k['name'], k['wp']) for k in out['keepers']])
