"""
2027 win value for every player.

- Talent lines from talent.py (per game / start / outing), scaled to a week.
- Average team = real 2023-26 average team week, adjusted to 2027 rules (ctx27.json).
- Opponents = every real 7-day team-week 2014-2026 (same 22 categories), each
  season rescaled to 2027 levels, weighted toward recent seasons (0.85 per year back).
- Swap him in for a replacement player at his role (12-team depth), replay, and
  measure added matchup win %. Per game = when he plays; Expected season = times availability.
"""
import json, glob, numpy as np, collections, sys
import talent
from weeks import load, IDS
from model import team_components, displayed, CATS, LOW, STEP

YEARS = [2014, 2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026]
G_WEEK, SP_WEEK, RP_WEEK, RP_IP_WEEK = 6.0, 1.25, 2.5, 3.5
TEAMS = 12
BANDS = {'H': (120, 150), 'SP': (105, 130), 'RP': (24, 40)}
ratio = json.load(open('ctx27.json'))

# ---------------------------------------------------------------- opponents
rows = [t for m in load(YEARS) for t in m if t['days'] == 7 and t.get('AB', 1) > 0 and t['IP'] and t['IP'] > 0]
AVGV = lambda t: t['H'] / t['AB'] if t.get('AB') else t['AVG']
recent = [t for t in rows if int(t['year']) >= 2023]
comps = [team_components(t) for t in recent]
avg = {k: float(np.mean([c[k] for c in comps])) for k in comps[0]}
for k, f in ratio.items():
    if k in avg: avg[k] *= f
avg['E'] *= 1; avg['A'] *= 1
target = displayed(avg)

opp = {k: [] for k in CATS}; wts = []
by_year = collections.defaultdict(list)
for t in rows: by_year[t['year']].append(t)
for y, ts in by_year.items():
    mean = {k: np.mean([(AVGV(t) if k == 'AVG' else t[k]) for t in ts]) for k in CATS}
    w = 0.85 ** (2026 - int(y))
    for t in ts:
        for k in CATS:
            v = AVGV(t) if k == 'AVG' else t[k]
            opp[k].append(v * (target[k] / mean[k]) if mean[k] else v)
        wts.append(w)
opp = {k: np.array(v) for k, v in opp.items()}
wts = np.array(wts); wts /= wts.sum()


def score(comp):
    d = displayed(comp)
    cw = np.zeros(len(wts)); per = {}
    for k in CATS:
        m = (opp[k] - d[k]) if k in LOW else (d[k] - opp[k])
        w = np.clip(0.5 + m / STEP[k], 0, 1)
        per[k] = float((w * wts).sum()); cw += w
    win = np.clip(cw - 10.5, 0, 1)
    return float((cw * wts).sum()), float((win * wts).sum()), per


# ---------------------------------------------------------------- QS model
def qs_model():
    sys.path.insert(0, '/home/claude/frank-cup/scripts'); import sources
    from model import norm
    yp = {}
    for f in sorted(glob.glob('/home/claude/research/research_out/season_P_*.json')):
        for p in sources._players(json.load(open(f))):
            v = p.get('s', {}).get('83')
            if v not in (None, '', '-'): yp.setdefault(norm(p['n']), float(v))
    X, Y = [], []
    for pid, (s, x) in talent.rows('/home/claude/research/research_out/history/seasons/2026_pitching.json').items():
        gs = s['gamesStarted']
        if gs < 10: continue
        q = yp.get(norm(x['player']['fullName']))
        if q is None: continue
        ip = talent.ipf(s['inningsPitched'])
        X.append([1, ip / gs, 9 * s['earnedRuns'] / ip]); Y.append(q / gs)
    return np.linalg.lstsq(np.array(X), np.array(Y), rcond=None)[0]


def weekly(p, qb):
    r = p['rate']
    if p['role'] == 'H':
        pa = p['pa_g']; f = G_WEEK * pa
        c = {k: r[k] * f for k in ('AB', 'H', 'D', 'T', 'HR', 'R', 'RBI', 'SB', 'BB', 'HBP', 'SF')}
        return {'H': c['H'], 'AB': c['AB'], 'R': c['R'], '3B': c['T'], 'HR': c['HR'], 'RBI': c['RBI'], 'SB': c['SB'],
                'BB': c['BB'], 'XBH': c['D'] + c['T'] + c['HR'], 'TB': c['H'] + c['D'] + 2 * c['T'] + 3 * c['HR'],
                'OB': c['H'] + c['BB'] + c['HBP'], 'PAO': c['AB'] + c['BB'] + c['HBP'] + c['SF']}
    n = SP_WEEK if p['role'] == 'SP' else min(RP_WEEK, RP_IP_WEEK / max(p['ip_out'], 0.3))
    bf = p['bf_out'] * n
    era = 9 * r['ER'] / r['IP']
    qs = float(np.clip(qb @ [1, p['ip_out'], era], 0, 0.9)) if p['role'] == 'SP' else 0.0
    return {'IP': p['ip_out'] * n, 'W': p['per']['W'] * n, 'L': p['per']['L'] * n, 'CG': p['per']['CG'] * n,
            'SV': p['per']['SV'] * n, 'HLD': p['per']['HLD'] * n, 'K': r['K'] * bf, 'ER': r['ER'] * bf,
            'BR': (r['HA'] + r['BB']) * bf, 'BBP': r['BB'] * bf, 'QS': qs * n}


def swap(line, repl):
    c = dict(avg)
    for k in line: c[k] = c[k] - repl[k] + line[k]
    return c


def run():
    T, LG = talent.build(); talent.durability(T)
    qb = qs_model()
    # who is in the player pool: a real 2027 role is plausible
    pool = []
    for key, p in T.items():
        if p['role'] == 'H':
            ok = p['mlb_pa'] >= 250 or (p['milb_pa'] >= 250 and p['age'] <= 27)
        else:
            ok = p['mlb_bf'] >= 150 or (p['milb_bf'] >= 250 and p['age'] <= 27)
        if ok:
            p['line'] = weekly(p, qb); pool.append(p)
    repl = {}
    for r in BANDS:
        ls = [p['line'] for p in pool if p['role'] == r]
        repl[r] = {k: float(np.median([l[k] for l in ls])) for k in ls[0]}
    for it in range(3):
        for p in pool:
            p['cw'], p['wp'], p['per'] = score(swap(p['line'], repl[p['role']]))
        for r, (a, b) in BANDS.items():
            ls = sorted([p for p in pool if p['role'] == r], key=lambda p: -p['wp'])[a:b]
            repl[r] = {k: float(np.mean([p['line'][k] for p in ls])) for k in ls[0]['line']}
    base = {r: score(swap(repl[r], repl[r])) for r in BANDS}
    for p in pool:
        cw, wp, per = score(swap(p['line'], repl[p['role']]))
        b = base[p['role']]
        p['cw'], p['wp'] = cw - b[0], wp - b[1]
        p['per'] = {k: per[k] - b[2][k] for k in CATS}
        p['wp_season'] = p['wp'] * p['avail'] * p['mlb_share']
    return pool, dict(avg=avg, target=target, n_opp=len(wts), repl=repl)


if __name__ == '__main__':
    pool, meta = run()
    print('opponent weeks', meta['n_opp'], 'pool', len(pool), collections.Counter(p['role'] for p in pool))
    for key in ('wp', 'wp_season'):
        print('----', key)
        for i, p in enumerate(sorted(pool, key=lambda p: -p[key])[:40]):
            print(f"{i+1:3d} {p['name'][:22]:22s} {p['role']:2s} age {p['age']:4.1f} pg {100*p['wp']:5.2f} season {100*p['wp_season']:5.2f} avail {p['avail']:.2f}{' R' if p['rookie'] else ''}")
