import json, pickle, glob, sys
sys.path.insert(0, '/home/claude/frank-cup/scripts')
from model import norm
pool, meta = pickle.load(open('v27.pkl', 'rb'))
REPO = '/home/claude/frank-cup'
cfg = json.load(open(f'{REPO}/league_config.json'))
tid = cfg['teamIds']['2026']
rd = json.load(open(f'{REPO}/raw/2026/players/week_26.json')); day = sorted(rd['days'])[-1]
owner = {}
for tk, t in rd['days'][day].items():
    for pl in t['players']:
        owner[('H' if pl['pt'] == 'B' else 'P', norm(pl['n']))] = tid[tk.split('.t.')[-1]]
def flat(b):
    o = {}
    for x in b:
        if isinstance(x, dict): o.update(x)
    return o
drafted = {}
d = json.load(open(f'{REPO}/raw/2026/draft_results.json'))['fantasy_content']['league'][1]['draft_results']
for i in range(d['count']):
    x = d[str(i)]['draft_result']; info = flat(x['0']['players']['0']['player'][0])
    side = 'H' if info.get('position_type') == 'B' else 'P'
    drafted[(side, norm(info['name']['full']))] = (x['round'], bool(info.get('is_keeper', {}).get('kept')))
ypos = {}
import sources
for side, pre in (('H', 'season_B'), ('P', 'season_P')):
    for f in sorted(glob.glob(f'/home/claude/research/research_out/{pre}_*.json')):
        for p in sources._players(json.load(open(f))): ypos.setdefault((side, norm(p['n'])), p['pos'])
for tk, t in rd['days'][day].items():
    for pl in t['players']: ypos[('H' if pl['pt'] == 'B' else 'P', norm(pl['n']))] = pl['pos']
teams = {t['id']: t['abbreviation'] for t in json.load(open('/home/claude/research/research_out/mlb/teams.json'))['teams']}
def rec(p):
    side = 'H' if p['role'] == 'H' else 'P'
    k = (side, norm(p['name']))
    dr = drafted.get(k)
    o = {'n': p['name'], 'role': p['role'], 'pos': ypos.get(k) or p['pos'] or p['role'], 'tm': teams.get(p['team'], ''), 'age': p['age'],
         'own': owner.get(k), 'rd': dr[0] if dr else None, 'kept': dr[1] if dr else False,
         'av': p['avail'], 'ms': p['mlb_share'], 'rk': p['rookie'], 'lt': p.get('long_term'),
         'il': {str(y): n for y, n in p.get('il_hist', {}).items()},
         'mlb': p.get('mlb_pa', p.get('mlb_bf')), 'mi': p.get('milb_pa', p.get('milb_bf')), 'lvl': p.get('top_level'),
         'per': {c: round(v, 3) for c, v in p['per'].items() if c not in ('A', 'E') and abs(v) >= 0.001}}
    return o
def board(key):
    ps = sorted(pool, key=lambda p: -p[key])[:900]
    out = []
    for i, p in enumerate(ps):
        o = rec(p); o['r'] = i + 1; o['wp'] = round(100 * p[key], 2)
        o['cw'] = round(p['cw'] * (p['avail'] * p['mlb_share'] if key == 'wp_season' else 1), 3)
        out.append(o)
    return out
old = json.load(open('rank.json'))
data = {'x27': board('wp_season'), 'p27': board('wp'), 'season': old['season'], 'managers': cfg['managers'],
        'rosterDay': day, 'weeks': old['weeks'], 'meta': {'opp': meta['n_opp'], 'pulled': '2026-09-30'}}
json.dump(data, open('rank27.json', 'w'), separators=(',', ':'), ensure_ascii=False)
print(len(data['x27']), sum(1 for p in data['x27'] if p['own']), 'owned in top 900')
print(data['x27'][0])
