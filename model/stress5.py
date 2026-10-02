"""Stress test 5: does the win engine match real results, and is the data clean?"""
import json, glob, collections, math, pickle, sys
import numpy as np
from scipy.stats import spearmanr
import talent, value27 as V, stress_lib as S
from weeks import load, IDS
from model import team_components, displayed, CATS, LOW, STEP, norm
REPO = '/home/claude/frank-cup'

print('=== A. engine vs real standings: every team-season with full box scores (2023-2026)')
rows = load(V.YEARS)
by = collections.defaultdict(list)          # (year, team) -> [(my week, cats won share, matchup result)]
season_weeks = collections.defaultdict(list)
for m in rows:
    if m[0]['days'] != 7 or not all(t.get('IP') and t.get('AB', 1) > 0 for t in m): continue
    for i, t in enumerate(m):
        o = m[1 - i]; sw = t['sw']
        w = sum(1.0 if v == t['key'] else 0.5 if v == 'TIE' else 0.0 for sid, v in sw.items() if sid in IDS)
        ow = sum(1.0 if v == o['key'] else 0.5 if v == 'TIE' else 0.0 for sid, v in sw.items() if sid in IDS)
        by[(t['year'], t['key'])].append((t, w, 1.0 if w > ow else 0.5 if w == ow else 0.0))
        season_weeks[t['year']].append(t)
AVGV = V.AVGV
pred_c, act_c, pred_m, act_m, yrs = [], [], [], [], []
for (y, tk), lst in by.items():
    if len(lst) < 12 or not all('H' in t and t.get('AB') for t, _, _ in lst): continue
    comps = [team_components(t) for t, _, _ in lst]
    avg = {k: float(np.mean([c[k] for c in comps])) for k in comps[0]}
    d = displayed(avg)
    opp = [t for t in season_weeks[y] if t['key'] != tk]
    cw = np.zeros(len(opp))
    for k in CATS:
        ov = np.array([AVGV(t) if k == 'AVG' else t[k] for t in opp], float)
        m_ = (ov - d[k]) if k in LOW else (d[k] - ov)
        cw += np.clip(0.5 + m_ / STEP[k], 0, 1)
    pred_c.append(cw.mean()); pred_m.append(np.clip(cw - 10.5, 0, 1).mean())
    act_c.append(np.mean([w for _, w, _ in lst])); act_m.append(np.mean([r for _, _, r in lst])); yrs.append(y)
pred_c, act_c, pred_m, act_m = map(np.array, (pred_c, act_c, pred_m, act_m))
print(f'team-seasons: {len(pred_c)}')
print(f'categories won per week: predicted vs real  corr {np.corrcoef(pred_c, act_c)[0, 1]:.3f}  avg miss {np.abs(pred_c - act_c).mean():.2f} cats (teams range {act_c.min():.1f} to {act_c.max():.1f})')
print(f'matchup win %:           predicted vs real  corr {np.corrcoef(pred_m, act_m)[0, 1]:.3f}  avg miss {100 * np.abs(pred_m - act_m).mean():.1f} points; predicted spread {pred_m.std():.3f} vs real {act_m.std():.3f}')
sl = np.polyfit(pred_m, act_m, 1); print(f'   real = {sl[0]:.2f} x predicted + {sl[1]:.2f}   (1.00 and 0.00 would be perfect)')

print('\n=== B. do player values add up to team results? 2026 final rosters')
rev, _ = S.actual(2026)
val = {S.nkey(p): 100 * p['wp'] for p in rev}
cfg = json.load(open(f'{REPO}/league_config.json')); tid = cfg['teamIds']['2026']
files = sorted(glob.glob(f'{REPO}/raw/2026/players/week_*.json'))
tot = collections.defaultdict(list)
for f in files:
    rd = json.load(open(f))
    for day in sorted(rd['days']):
        for tk, t in rd['days'][day].items():
            vs = sorted([val.get(('H' if pl['pt'] == 'B' else 'P', norm(pl['n'])), 0.0) for pl in t['players']], reverse=True)
            tot[tk].append(sum(max(v, 0) for v in vs[:19]))
st = json.load(open(f'{REPO}/raw/2026/standings.json'))['fantasy_content']['league'][1]['standings'][0]['teams']
rec = {}
for k, v in st.items():
    if k == 'count': continue
    t = v['team']; tk = S.flat(t[0])['team_key']; o = t[2]['team_standings']['outcome_totals']
    rec[tk] = (float(o['percentage']), int(t[2]['team_standings']['rank']), S.flat(t[0])['name'])
ks = sorted(rec, key=lambda k: rec[k][1])
tv = [np.mean(tot[k]) for k in ks]
for k, v in zip(ks, tv): print(f'   {rec[k][1]:2d} {rec[k][2][:26]:26s} win% {rec[k][0]:.3f}  roster value (weeks 20-26) {v:5.1f}')
print(f'   roster value vs season win%: corr {np.corrcoef(tv, [rec[k][0] for k in ks])[0, 1]:.2f}, rank corr {spearmanr(tv, [rec[k][0] for k in ks])[0]:.2f}')

print('\n=== C. data checks on the 2027 board')
pool, meta = pickle.load(open('v27.pkl', 'rb'))
top = sorted(pool, key=lambda p: -p['wp_season']); rk = {id(p): i + 1 for i, p in enumerate(top)}
T300 = top[:300]
bad = [p['name'] for p in pool if any(isinstance(p.get(k), float) and (math.isnan(p[k]) or math.isinf(p[k])) for k in ('wp', 'wp_season', 'avail', 'cw', 'keep3'))]
print('broken numbers:', len(bad), bad[:5])
names = collections.defaultdict(list)
for p in top[:900]: names[S.nkey(p)].append(p)
dups = {k: v for k, v in names.items() if len(v) > 1}
print('same name, same side, both on the board:', [(v[0]['name'], [(rk[id(x)], x['role'], x['age']) for x in v]) for v in dups.values()])
print('top 300 with no team:', [p['name'] for p in T300 if not p.get('team')])
print('top 300 with no birth date (age guessed):', [p['name'] for p in T300 if not (talent.people.get(p['id']) or {}).get('birth')])
print('top 300 hitters with no position:', [p['name'] for p in T300 if p['role'] == 'H' and p.get('prim') in (None, 'DH')])
idle = [p for p in T300 if (p['role'] == 'H' and p['pa_y0'] == 0) or (p['role'] != 'H' and p['g_y0'] == 0)]
print('top 300 who did not play in MLB in 2026:')
for p in idle: print(f"   #{rk[id(p)]:3d} {p['name'][:24]:24s} {p['role']:2s} age {p['age']} healthy {p['avail']} role share {p['mlb_share']} top level {p.get('top_level')} {p.get('pipeline', '')} {p.get('long_term', '') or ''}")
print('top 216 not expected to hold a full MLB job:', [(rk[id(p)], p['name'], p['mlb_share']) for p in top[:216] if p['mlb_share'] < 1])
# pitcher role: assigned vs what he did last season
flips = []
p26 = talent.rows(f'{talent.H}/seasons/2026_pitching.json')
for p in T300:
    if p['role'] == 'H' or p['id'] not in p26: continue
    s = p26[p['id']][0]; g, gs = s['gamesPlayed'], s['gamesStarted']
    last = 'SP' if gs >= 0.5 * g else 'RP'
    if last != p['role'] or 0.25 < gs / max(g, 1) < 0.75: flips.append((rk[id(p)], p['name'], p['role'], f'{gs} starts in {g} games in 2026'))
print('pitchers whose role is a judgment call:', flips)
oh = [(rk[id(p)], p['role'], round(100 * p['wp_season'], 2)) for p in pool if p['name'] == 'Shohei Ohtani']
print('Ohtani entries (hitter and pitcher are separate):', oh)
# rostered in the league but missing from the board
rd = json.load(open(files[-1])); day = sorted(rd['days'])[-1]
allnames = {S.nkey(p) for p in pool}
miss = [(pl['n'], pl['pos']) for tk, t in rd['days'][day].items() for pl in t['players'] if ('H' if pl['pt'] == 'B' else 'P', norm(pl['n'])) not in allnames]
print('on a league roster at season end but not on the board:', miss)
h216 = [p for p in top[:216]]
print('top 216 mix:', collections.Counter(p['role'] for p in h216), ' league slots would be 120 hitters / 96 pitchers')
print('grade check: avg value of top 216 =', round(100 * np.mean([p['wp_season'] for p in h216]), 3), '| hitters ranked 121-150 avg grade', round(np.mean([p['g_draft'] for p in [x for x in top if x['role'] == 'H'][120:150]]), 1),
      '| SP 106-130', round(np.mean([p['g_draft'] for p in [x for x in top if x['role'] == 'SP'][105:130]]), 1), '| RP 25-40', round(np.mean([p['g_draft'] for p in [x for x in top if x['role'] == 'RP'][24:40]]), 1))
