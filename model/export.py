import json, sys
sys.path.insert(0, '.')
from model import *
teams = {t['id']: t['abbreviation'] for t in json.load(open(f'{RES}/mlb/teams.json'))['teams']}
import datetime as dt
pulled = json.load(open(f'{RES}/mlb/meta.json'))['pulled']
WEEKS = ((dt.date.fromisoformat(pulled) - dt.date(2026, 3, 25)).days) / 7
main, meta = build('2026_season', '2025_2h', min_raw={'H': 150, 'SP': 8, 'RP': 20})
season, _ = build('2026_season', None, min_pa=1, min_gs=1, min_rp=1, season_weeks=WEEKS)
sea = {(p['role'] if p['role']=='H' else 'P', p['id']): p for p in season}

# Frank Cup rosters: latest day of the newest roster file
import glob as _g
rf = sorted(_g.glob('/home/claude/frank-cup/raw/2026/players/week_*.json'))[-1]
rd = json.load(open(rf))
day = sorted(rd['days'])[-1]
tid = json.load(open('/home/claude/frank-cup/league_config.json'))['teamIds']['2026']
owner = {}
for tk, t in rd['days'][day].items():
    mgr = tid.get(tk.split('.t.')[-1], tk)
    for pl in t['players']:
        owner[('H' if pl['pt'] == 'B' else 'P', norm(pl['n']))] = mgr
trend, _ = build('last60', None, min_pa=40, min_gs=3, min_rp=8)
tr = {(p['role'] if p['role']=='H' else 'P', p['id']): p for p in trend}
# rank within role for trend
out = []
for p in main:
    t = tr.get((p['role'] if p['role']=='H' else 'P', p['id']))
    out.append({'r': p['rank'], 'n': p['name'], 'role': p['role'], 'pos': p['ypos'] or p['pos'],
                'tm': teams.get(p['team'], ''), 'wp': round(100 * p['wp'], 2), 'cw': round(p['cw'], 3),
                'y': p['yahoo'], 'tw': round(100 * t['wp'], 2) if t else None,
                'g': p['G'], 'pa': p['PA'], 'gs': p['GS'], 'ip': round(p['IP'], 1) if p['IP'] else None,
                'per': {k: round(v, 3) for k, v in p['per'].items() if k not in ('A', 'E') and abs(v) >= 0.001}})
def side(o): return 'H' if o['role'] == 'H' else 'P'
for o, p in zip(out, main):
    o['own'] = owner.get((side(o), norm(p['name'])))
# season-total board: its own ranking, compared to Yahoo
sout = []
for p in season:
    sout.append({'n': p['name'], 'role': p['role'], 'pos': p['ypos'] or p['pos'], 'tm': teams.get(p['team'], ''),
                 'wp': round(100 * p['wp'], 2), 'cw': round(p['cw'], 3), 'y': p['yahoo'],
                 'g': p['G'], 'pa': p['PA'], 'gs': p['GS'], 'ip': round(p['IP'], 1) if p['IP'] else None,
                 'own': owner.get(('H' if p['role'] == 'H' else 'P', norm(p['name']))),
                 'per': {k: round(v, 3) for k, v in p['per'].items() if k not in ('A', 'E') and abs(v) >= 0.001}})
cnt = {'H': 0, 'P': 0}
for i, o in enumerate(sout):
    o['r'] = i + 1; cnt[side(o)] += 1; o['sr'] = cnt[side(o)]
# rank within side (hitters / pitchers) to line up with Yahoo's separate B and P lists
cnt = {'H': 0, 'P': 0}
for o in out:
    side = 'H' if o['role'] == 'H' else 'P'
    cnt[side] += 1; o['sr'] = cnt[side]
# rank trend
ts = sorted([o for o in out if o['tw'] is not None], key=lambda o: -o['tw'])
for i, o in enumerate(ts): o['tr'] = i + 1
json.dump({'meta': {'weeks': meta['weeks'], 'pulled': json.load(open(f'{RES}/mlb/meta.json'))['pulled']},
           'players': out, 'season': sout, 'rosterDay': day, 'weeks': round(WEEKS, 1),
           'managers': json.load(open('/home/claude/frank-cup/league_config.json'))['managers']}, open('rank.json', 'w'), separators=(',', ':'), ensure_ascii=False)
print(len(out))
for o in out[:25]: print(o['r'], o['n'], o['role'], o['wp'], o['y'], o.get('tr'))
