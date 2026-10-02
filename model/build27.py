"""Full build: 2027 projection (+2028, 2029 for keeper value), the 2026 review, grades, and the board data."""
import datetime as dt, json, glob, pickle, sys, collections
import numpy as np
import talent, value27 as V
from model import norm
sys.path.insert(0, '/home/claude/frank-cup/scripts'); import sources

REPO = '/home/claude/frank-cup'; RES = '/home/claude/research/research_out'


def key(p): return (p['role'] == 'H', p['id'])


def rostered():
    """everyone on a league roster on the last day of the season"""
    rd = json.load(open(sorted(glob.glob(f'{REPO}/raw/2026/players/week_*.json'))[-1])); day = sorted(rd['days'])[-1]
    return {('H' if pl['pt'] == 'B' else 'P', norm(pl['n'])) for t in rd['days'][day].values() for pl in t['players']}


def project(y):
    talent.AGE_DATE = dt.date(y, 7, 1)
    talent.CARRY_ON = (y == 2027)          # finishing 2026 on the injured list only weighs on 2027
    T, _ = talent.build(); talent.durability(T); talent.team_context(T); talent.pedigree(T); talent.fielding(T)
    for p in T.values():
        if p.get('mlb_share', 1) < 1 and not p.get('absent'): p['mlb_share'] = round(min(1.0, p['mlb_share'] + 0.4 * (y - 2027)), 2)
    pool, meta = V.run(T, also=ROSTERED)
    talent.CARRY_ON = True
    return {key(p): p for p in pool}, meta


ROSTERED = rostered()


def grade(vals, n_start):
    """100 = the average starter, 80 = a free agent (replacement), and every 20 points is
    one more average-starter's worth of value above replacement."""
    mu = float(np.mean(sorted(vals, reverse=True)[:n_start]))
    return lambda v: int(round(100 + 20 * (v - mu) / mu)), mu


# ------------------------------------------------------------ 2027 (+ keeper years)
V.set_context(2027)
y27, meta = project(2027)
y28, _ = project(2028)
y29, _ = project(2029)
for k, p in y27.items():
    p['wp28'] = y28[k]['wp_season'] if k in y28 else 0.0
    p['wp29'] = y29[k]['wp_season'] if k in y29 else 0.0
    p['keep3'] = p['wp_season'] + 0.8 * p['wp28'] + 0.6 * p['wp29']
pool = list(y27.values())
N27 = 12 * 18
g_draft, mu_d = grade([p['wp_season'] for p in pool], N27)
g_game, mu_g = grade([p['wp'] for p in pool], N27)
g_keep, mu_k = grade([p['keep3'] for p in pool], N27)
for p in pool:
    p['g_draft'], p['g_game'], p['g_keep'] = g_draft(p['wp_season']), g_game(p['wp']), g_keep(p['keep3'])
pickle.dump((pool, meta), open('v27.pkl', 'wb'))

# ------------------------------------------------------------ 2026 in review (what actually happened)
talent.SEASONS = {2026: 1}; talent.MILB_W = {}; talent.PRIOR_PA = talent.PRIOR_BF = 1
talent.AGE_ON = False; talent.PEDIGREE_ON = False; talent.AGE_DATE = dt.date(2026, 7, 1)
talent.OUT_PRIOR_SP = talent.OUT_PRIOR_RP = talent.PAG_PRIOR = 0.001
talent.FIELD_PRIOR_A = talent.FIELD_PRIOR_E = 0.001
T26, _ = talent.build(); talent.fielding(T26)
V.set_context(2026)
WEEKS = 26.7
rev, _ = V.run(T26, actual_weeks=WEEKS, teams=10,
               pool_filter=lambda p: (p['pa_y0'] >= 30) if p['role'] == 'H' else (p['g_y0'] >= 5))
g_rev, mu_r = grade([p['wp'] for p in rev], 10 * 19)

# ------------------------------------------------------------ league info: owners, draft round, Yahoo
cfg = json.load(open(f'{REPO}/league_config.json')); tid = cfg['teamIds']['2026']
rd = json.load(open(sorted(glob.glob(f'{REPO}/raw/2026/players/week_*.json'))[-1])); day = sorted(rd['days'])[-1]
owner, ypos = {}, {}
for side, pre in (('H', 'season_B'), ('P', 'season_P')):
    for f in sorted(glob.glob(f'{RES}/{pre}_*.json')):
        for p in sources._players(json.load(open(f))): ypos.setdefault((side, norm(p['n'])), p['pos'])
yrank = {}
for side, pre in (('H', 'season_B'), ('P', 'season_P')):
    for i, p in enumerate([p for f in sorted(glob.glob(f'{RES}/{pre}_*.json')) for p in sources._players(json.load(open(f)))]):
        yrank.setdefault((side, norm(p['n'])), i + 1)
for tk, t in rd['days'][day].items():
    for pl in t['players']:
        k = ('H' if pl['pt'] == 'B' else 'P', norm(pl['n']))
        owner[k] = tid[tk.split('.t.')[-1]]; ypos[k] = pl['pos']
def flat(b):
    o = {}
    for x in b:
        if isinstance(x, dict): o.update(x)
    return o
drafted = {}
d = json.load(open(f'{REPO}/raw/2026/draft_results.json'))['fantasy_content']['league'][1]['draft_results']
for i in range(d['count']):
    x = d[str(i)]['draft_result']; info = flat(x['0']['players']['0']['player'][0])
    drafted[('H' if info.get('position_type') == 'B' else 'P', norm(info['name']['full']))] = (x['round'], bool(info.get('is_keeper', {}).get('kept')))
teams = {t['id']: t['abbreviation'] for t in json.load(open(f'{RES}/mlb/teams.json'))['teams']}


def base(p):
    k = ('H' if p['role'] == 'H' else 'P', norm(p['name']))
    el = '/'.join(x for x in ('C', '1B', '2B', '3B', 'SS', 'OF') if x in p.get('el', ())) or ('Util' if p['role'] == 'H' else p['role'])
    return k, {'n': p['name'], 'role': p['role'], 'pos': ypos.get(k) or el, 'tm': teams.get(p['team'], ''),
               'own': owner.get(k), 'vs': p.get('vs'),
               'per': {c: round(v, 3) for c, v in p['per'].items() if c != 'CG' and abs(v) >= 0.001}}


def rec27(p, val, gkey):
    k, o = base(p)
    dr = drafted.get(k)
    o.update({'age': p['age'], 'rd': dr[0] if dr else None, 'kept': dr[1] if dr else False, 'av': p['avail'], 'ms': p['mlb_share'],
              'rk': p['rookie'], 'lt': p.get('long_term'), 'eil': p.get('ended_il'), 'abs': p.get('absent'), 'il': {str(y): n for y, n in p.get('il_hist', {}).items()},
              'mlb': p.get('mlb_pa', p.get('mlb_bf')), 'mi': p.get('milb_pa', p.get('milb_bf')), 'lvl': p.get('top_level'),
              'pl': p.get('pipeline'), 'wp': round(100 * p[val], 2), 'g': p[gkey], 'gk': p['g_keep'], 'gg': p['g_game'], 'gd': p['g_draft'],
              'cw': round(p['cw'] * (p['avail'] * p['mlb_share'] if val == 'wp_season' else 1), 3)})
    return o


def board(val, gkey):
    out = [rec27(p, val, gkey) for p in sorted(pool, key=lambda p: -p[val])[:900]]
    for i, o in enumerate(out): o['r'] = i + 1
    return out


season = []
cnt = {'H': 0, 'P': 0}
for i, p in enumerate(sorted(rev, key=lambda p: -p['wp'])):
    k, o = base(p)
    side = k[0]; cnt[side] += 1
    o.update({'r': i + 1, 'sr': cnt[side], 'y': yrank.get(k), 'wp': round(100 * p['wp'], 2), 'cw': round(p['cw'], 3), 'g': g_rev(p['wp']),
              'gp': p['g_y0'], 'pa': p.get('pa_y0'), 'gs': p.get('gs_y0'), 'ip': round(p['ip_out'] * (p.get('gs_y0') if p['role'] == 'SP' else p['g_y0']), 1) if p['role'] != 'H' else None})
    season.append(o)

data = {'x27': board('wp_season', 'g_draft'), 'p27': board('wp', 'g_game'), 'season': season, 'managers': cfg['managers'],
        'rosterDay': day, 'weeks': WEEKS, 'meta': {'opp': meta['n_opp'], 'pulled': json.load(open(f'{RES}/history/meta.json'))['pulled']}}
json.dump(data, open('rank27.json', 'w'), separators=(',', ':'), ensure_ascii=False)
print('avg starter value: draft', round(100 * mu_d, 2), 'per game', round(100 * mu_g, 2), 'keeper', round(100 * mu_k, 2), '2026 review', round(100 * mu_r, 2))
for o in data['x27'][:30]: print(o['r'], o['n'], o['role'], o['pos'], 'grade', o['g'], 'pg', o['gg'], 'keep', o['gk'])
print('2026 review top:', [(o['r'], o['n'], o['g'], o['y']) for o in season[:15]])
print('grade spread draft: p10/p50/p90 of top 216:', np.percentile([o['g'] for o in data['x27'][:216]], [10, 50, 90]))
print('DONE')
