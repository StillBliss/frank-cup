"""
Win value for every player.

- Talent lines from talent.py (per game / start / outing), scaled to a week.
- Average team = real 2023-26 average team week, adjusted to the league's rules (ctx27.json for 2027).
- Opponents = every real 7-day team-week 2014-2026 (same 22 categories), each season
  rescaled to the target year's levels, weighted toward recent seasons (0.85 per year back).
- Swap him in for a replacement player (the hitters or pitchers just past the rostered
  ones), replay, and measure added matchup win %. Hitting uses one baseline for all hitters.
- Assists and Errors count as a small adjustment, judged against leftover players at the
  same position, so they only separate otherwise similar hitters.
  Complete games are held neutral.
"""
import json, glob, numpy as np, collections, sys
import talent
from weeks import load, IDS
from model import team_components, displayed, CATS, LOW, STEP, norm

YEARS = [2014, 2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026]
G_WEEK, SP_WEEK, RP_WEEK, RP_IP_WEEK = 6.0, 1.25, 2.5, 3.5
HSLOTS = {'C': 1, '1B': 1, '2B': 1, '3B': 1, 'SS': 1, 'OF': 3, 'Util': 2}     # per team
PBANDS = {12: {'SP': (105, 130), 'RP': (24, 40)}, 10: {'SP': (88, 110), 'RP': (26, 42)}}
ORDER = ('C', 'SS', '2B', '3B', '1B', 'OF')
ratio = json.load(open('ctx27.json'))
AVGV = lambda t: t['H'] / t['AB'] if t.get('AB') else t['AVG']
_rows = [t for m in load(YEARS) for t in m if t['days'] == 7 and t.get('AB', 1) > 0 and t['IP'] and t['IP'] > 0]
avg = target = opp = wts = None


def set_context(year=2027):
    """2027: 12 teams and the new pitching slots. 2026: the league as it was."""
    global avg, target, opp, wts
    comps = [team_components(t) for t in _rows if int(t['year']) >= 2023]
    avg = {k: float(np.mean([c[k] for c in comps])) for k in comps[0]}
    if year == 2027:
        for k, f in ratio.items():
            if k in avg: avg[k] *= f
    target = displayed(avg)
    o = {k: [] for k in CATS}; w_ = []
    by_year = collections.defaultdict(list)
    for t in _rows: by_year[t['year']].append(t)
    for y, ts in by_year.items():
        mean = {k: np.mean([(AVGV(t) if k == 'AVG' else t[k]) for t in ts]) for k in CATS}
        w = 0.85 ** (2026 - int(y))
        for t in ts:
            for k in CATS:
                v = AVGV(t) if k == 'AVG' else t[k]
                o[k].append(v * (target[k] / mean[k]) if mean[k] else v)
            w_.append(w)
    opp = {k: np.array(v) for k, v in o.items()}
    wts = np.array(w_); wts /= wts.sum()


set_context(2027)


def score(comp):
    d = displayed(comp)
    cw = np.zeros(len(wts)); per = {}
    for k in CATS:
        m = (opp[k] - d[k]) if k in LOW else (d[k] - opp[k])
        w = np.clip(0.5 + m / STEP[k], 0, 1)
        per[k] = float((w * wts).sum()); cw += w
    win = np.clip(cw - 10.5, 0, 1)
    return float((cw * wts).sum()), float((win * wts).sum()), per


# ---------------------------------------------------------------- QS
_YQS = None
def yahoo_qs():
    global _YQS
    if _YQS is None:
        sys.path.insert(0, '/home/claude/frank-cup/scripts'); import sources
        _YQS = {}
        for f in sorted(glob.glob('/home/claude/research/research_out/season_P_*.json')):
            for p in sources._players(json.load(open(f))):
                v = p.get('s', {}).get('83')
                if v not in (None, '', '-'): _YQS.setdefault(norm(p['n']), float(v))
    return _YQS


def qs_model():
    yp = yahoo_qs(); X, Y = [], []
    for pid, (s, x) in talent.rows('/home/claude/research/research_out/history/seasons/2026_pitching.json').items():
        gs = s['gamesStarted']
        if gs < 10: continue
        q = yp.get(norm(x['player']['fullName']))
        if q is None: continue
        ip = talent.ipf(s['inningsPitched'])
        X.append([1, ip / gs, 9 * s['earnedRuns'] / ip]); Y.append(q / gs)
    return np.linalg.lstsq(np.array(X), np.array(Y), rcond=None)[0]


def weekly(p, qb, actual_weeks=None):
    """projection: a full healthy week. actual_weeks: his real season total spread over the season."""
    r = p['rate']
    if p['role'] == 'H':
        games = (p['g_y0'] / actual_weeks) if actual_weeks else G_WEEK
        f = (p['pa_y0'] / actual_weeks) if actual_weeks else G_WEEK * p['pa_g']
        c = {k: r[k] * f for k in ('AB', 'H', 'D', 'T', 'HR', 'R', 'RBI', 'SB', 'BB', 'HBP', 'SF')}
        return {'H': c['H'], 'AB': c['AB'], 'R': c['R'], '3B': c['T'], 'HR': c['HR'], 'RBI': c['RBI'], 'SB': c['SB'],
                'BB': c['BB'], 'XBH': c['D'] + c['T'] + c['HR'], 'TB': c['H'] + c['D'] + 2 * c['T'] + 3 * c['HR'],
                'OB': c['H'] + c['BB'] + c['HBP'], 'PAO': c['AB'] + c['BB'] + c['HBP'] + c['SF'],
                'A': p.get('a_g', 0.0) * games, 'E': p.get('e_g', 0.0) * games}
    if actual_weeks:
        n = (p['gs_y0'] if p['role'] == 'SP' else p['g_y0']) / actual_weeks
    else:
        n = SP_WEEK if p['role'] == 'SP' else min(RP_WEEK, RP_IP_WEEK / max(p['ip_out'], 0.3))
    bf = p['bf_out'] * n
    era = 9 * r['ER'] / r['IP']
    qs = float(np.clip(qb @ [1, p['ip_out'], era], 0, 0.9)) if p['role'] == 'SP' else 0.0
    if actual_weeks and p['role'] == 'SP' and p['gs_y0']:
        q = yahoo_qs().get(norm(p['name']))
        if q is not None: qs = q / p['gs_y0']
    return {'IP': p['ip_out'] * n, 'W': p['dec']['W'] * n, 'L': p['dec']['L'] * n,
            'SV': p['dec']['SV'] * n, 'HLD': p['dec']['HLD'] * n, 'K': r['K'] * bf, 'ER': r['ER'] * bf,
            'BR': (r['HA'] + r['BB']) * bf, 'BBP': r['BB'] * bf, 'QS': qs * n}


def swap(line, repl):
    c = dict(avg)
    for k in line:
        if k[0] != '_': c[k] = max(0.0, c[k] - repl[k] + line[k])   # a team can't have negative holds
    return c


def mean_line(ps):
    return {k: float(np.mean([p['line'][k] for p in ps])) for k in ps[0]['line'] if not k.startswith('_')}


def run(T=None, actual_weeks=None, teams=12, pool_filter=None):
    if T is None:
        T, LG = talent.build(); talent.durability(T); talent.team_context(T); talent.pedigree(T); talent.fielding(T)
    qb = qs_model()
    pool = []
    for key, p in T.items():
        if pool_filter: ok = pool_filter(p)
        elif p['role'] == 'H': ok = p['mlb_pa'] >= 250 or (p['milb_pa'] >= 250 and p['age'] <= 27)
        else: ok = p['mlb_bf'] >= 150 or (p['milb_bf'] >= 250 and p['age'] <= 27)
        if ok:
            p['line'] = weekly(p, qb, actual_weeks); pool.append(p)
    H = [p for p in pool if p['role'] == 'H']
    worth = (lambda p: p['wp']) if actual_weeks else (lambda p: p['wp'] * p.get('avail', 1) * p.get('mlb_share', 1))
    real = (lambda p: True) if actual_weeks else (lambda p: p.get('mlb_share', 1) >= 0.7)
    base = score(avg)

    # start: one generic replacement per role
    repl = {}
    for r in ('H', 'SP', 'RP'):
        ps = [p for p in pool if p['role'] == r]
        repl[r] = {k: float(np.median([p['line'][k] for p in ps])) for k in ps[0]['line']}
    for p in pool:
        p['wp'] = score(swap(p['line'], repl[p['role']]))[1] - base[1]
    hrepl = {}
    for it in range(3):
        # pitchers: replacement = the band just past the rostered ones
        for r, (a, b) in PBANDS[teams].items():
            ls = sorted([p for p in pool if p['role'] == r], key=lambda p: -worth(p))
            repl[r] = mean_line([p for p in ls if real(p)][a:b])
        # hitters: ONE hitting baseline for everyone (the hitters just past the rostered ones)...
        hs = [p for p in sorted(H, key=lambda p: -worth(p)) if real(p)]
        n_h = sum(HSLOTS.values()) * teams
        repl['H'] = mean_line(hs[n_h:n_h + 30])
        # ...and fielding judged only against the leftover players at his own position
        for pos in ORDER:
            c = [p for p in hs[n_h:] if p.get('prim') == pos][:8]
            hrepl[pos] = {'A': float(np.mean([p['line']['A'] for p in c])), 'E': float(np.mean([p['line']['E'] for p in c])),
                          '_who': [p['name'] for p in c]}
        hrepl['DH'] = {'A': 0.0, 'E': 0.0, '_who': []}
        for p in pool:
            if p['role'] == 'H':
                f = hrepl.get(p.get('prim'), hrepl['DH'])
                r = dict(repl['H'], A=f['A'], E=f['E'])
                if p.get('prim') in (None, 'DH'): r['A'], r['E'] = p['line']['A'], p['line']['E']   # a DH is neutral on defense
                cw, wp, per = score(swap(p['line'], r)); p['vs'] = p.get('prim') or 'DH'
            else:
                cw, wp, per = score(swap(p['line'], repl[p['role']])); p['vs'] = p['role']
            p['cw'], p['wp'] = cw - base[0], wp - base[1]
            p['per'] = {k: per[k] - base[2][k] for k in CATS}
    for p in pool:
        p['wp_season'] = p['wp'] * p.get('avail', 1) * p.get('mlb_share', 1)
    return pool, dict(avg=avg, target=target, n_opp=len(wts), repl=repl, hrepl=hrepl)


if __name__ == '__main__':
    pool, meta = run()
    print('opponent weeks', meta['n_opp'], 'pool', len(pool), collections.Counter(p['role'] for p in pool))
    for pos, l in meta['hrepl'].items(): print(pos, {k: round(v, 2) for k, v in l.items() if k in ('A', 'E')}, l['_who'])
    top = sorted(pool, key=lambda p: -p['wp_season'])
    print(collections.Counter(p['role'] for p in top[:216]), collections.Counter(p.get('prim') for p in top[:216] if p['role'] == 'H'))
    for i, p in enumerate(top[:45]):
        print(f"{i+1:3d} {p['name'][:22]:22s} {p['role']:2s} {'/'.join(sorted(p.get('el', [])))[:9]:9s} vs {p['vs']:4s} pg {100*p['wp']:5.2f} season {100*p['wp_season']:5.2f} A {100*p['per'].get('A',0):5.1f} E {100*p['per'].get('E',0):5.1f}")
