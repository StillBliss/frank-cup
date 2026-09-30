"""
Per-game "win value" model for The Frank Cup (personal tool, not the site).

1. Baseline: every real 7-day regular-season team-week (2023-2026). The average
   team week is the swap target; all real team-weeks are the opponents.
2. Player: per-game rates (hitter per game, SP per start, RP per appearance)
   scaled to a typical week.
3. Swap him in for a replacement-level player at his role, replay vs every
   opponent week. A and E are held at baseline (neutral).
4. Output: added category wins per week and added matchup win %.
"""
import json, glob, os, sys, unicodedata, re
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from weeks import load

RES = '/home/claude/research/research_out'
G_WEEK = 6.0      # hitter games in a typical week
SP_WEEK = 1.25    # starts per week for a rotation SP
RP_WEEK = 2.5     # appearances per week for a one-inning reliever
RP_IP_WEEK = 3.5  # weekly innings cap for bulk/long relievers
W_PRIOR = 0.5     # weight on the fallback window (2025 second half)
PRIOR = {'H': ('PA', 120), 'SP': ('GS', 6), 'RP': ('G', 15)}  # regression toward the role average
HBP_SF = 1.02     # (AB+BB+HBP+SF)/(AB+BB), team-level estimate for OBP denominators
N_REPL = {'H': (100, 130), 'SP': (55, 75), 'RP': (35, 50)}  # replacement rank band
LOW = {'E', 'L', 'ERA', 'WHIP'}
STEP = {'AVG': .001, 'OPS': .001, 'ERA': .01, 'WHIP': .01, 'KBB': .01, 'IP': 1 / 3}
STEP = {k: STEP.get(k, 1.0) for k in ['R', '3B', 'HR', 'RBI', 'SB', 'BB', 'A', 'E', 'AVG', 'OPS', 'XBH',
                                      'IP', 'W', 'L', 'CG', 'SV', 'K', 'HLD', 'ERA', 'WHIP', 'KBB', 'QS']}
CATS = ['R', '3B', 'HR', 'RBI', 'SB', 'BB', 'A', 'E', 'AVG', 'OPS', 'XBH',
        'IP', 'W', 'L', 'CG', 'SV', 'K', 'HLD', 'ERA', 'WHIP', 'KBB', 'QS']
COMP = ['H', 'AB', 'R', '3B', 'HR', 'RBI', 'SB', 'BB', 'A', 'E', 'XBH', 'TB', 'OB', 'PAO',
        'IP', 'W', 'L', 'CG', 'SV', 'K', 'HLD', 'ER', 'BR', 'BBP', 'QS']


# ---------------------------------------------------------------- team weeks
def team_components(t):
    c = {k: t[k] for k in ('H', 'AB', 'R', '3B', 'HR', 'RBI', 'SB', 'BB', 'A', 'E', 'XBH',
                            'IP', 'W', 'L', 'CG', 'SV', 'K', 'HLD', 'QS')}
    dbl = t['XBH'] - t['3B'] - t['HR']
    c['TB'] = t['H'] + dbl + 2 * t['3B'] + 3 * t['HR']
    c['PAO'] = (t['AB'] + t['BB']) * HBP_SF
    c['OB'] = (t['OPS'] - c['TB'] / t['AB']) * c['PAO']
    c['ER'] = t['ERA'] * t['IP'] / 9
    c['BR'] = t['WHIP'] * t['IP']
    c['BBP'] = t['K'] / t['KBB'] if t['KBB'] else 0
    return c


def displayed(c):
    """component dict or arrays -> the 22 category values"""
    return {
        'R': c['R'], '3B': c['3B'], 'HR': c['HR'], 'RBI': c['RBI'], 'SB': c['SB'], 'BB': c['BB'],
        'A': c['A'], 'E': c['E'], 'AVG': c['H'] / c['AB'], 'OPS': c['OB'] / c['PAO'] + c['TB'] / c['AB'],
        'XBH': c['XBH'], 'IP': c['IP'], 'W': c['W'], 'L': c['L'], 'CG': c['CG'], 'SV': c['SV'],
        'K': c['K'], 'HLD': c['HLD'], 'ERA': 9 * c['ER'] / c['IP'], 'WHIP': c['BR'] / c['IP'],
        'KBB': c['K'] / np.maximum(c['BBP'], 1e-9), 'QS': c['QS']}


def baseline():
    rows = [t for m in load() for t in m if t['days'] == 7 and t['AB'] > 0 and t['IP'] > 0]
    comps = [team_components(t) for t in rows]
    avg = {k: float(np.mean([c[k] for c in comps])) for k in COMP}
    # opponents: Yahoo's displayed values (what the real week was decided on)
    opp = {k: np.array([t[k] if k != 'AVG' else t['H'] / t['AB'] for t in rows], float) for k in CATS}
    return avg, opp, len(rows)


def score(comp, opp):
    """category wins (ties = half) and matchup win share for one team vs every opponent"""
    d = displayed(comp)
    n = len(opp['R'])
    cw = np.zeros(n)
    per = {}
    for k in CATS:
        x, y = d[k], opp[k]
        m = (y - x) if k in LOW else (x - y)
        # smooth step: an expected-value total vs a whole-number (or rounded) opponent total.
        # equivalent to jittering our total by +-half a display unit.
        w = np.clip(0.5 + m / STEP[k], 0, 1)
        per[k] = w.mean()
        cw += w
    win = np.clip(cw - 10.5, 0, 1)   # 11.5+ wins, 10.5- loses, 11 = tie (half), smooth in between
    return cw.mean(), win.mean(), per


# ---------------------------------------------------------------- players
def norm(s):
    s = re.sub(r'\(.*?\)', '', s)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\b(jr|sr|ii|iii|iv)\b\.?', '', s)
    return re.sub(r'[^a-z]', '', s)


def ip(v):
    a, _, b = str(v).partition('.')
    return int(a) + int(b or 0) / 3


def mlb_rows(win, group):
    return json.load(open(f'{RES}/mlb/{win}_{group}.json'))['stats'][0]['splits']


def yahoo(prefix):
    sys.path.insert(0, '/home/claude/frank-cup/scripts')
    import sources
    out = []
    for f in sorted(glob.glob(f'{RES}/{prefix}_*.json')):
        out += sources._players(json.load(open(f)))
    return out


HK = ['G', 'PA', 'AB', 'H', 'R', 'D', 'T', 'HR', 'RBI', 'SB', 'BB', 'HBP', 'SF', 'TB']
PK = ['G', 'GS', 'IP', 'W', 'L', 'CG', 'SV', 'HLD', 'K', 'ER', 'HA', 'BBA', 'QS']


def hcounts(s):
    return dict(G=s['gamesPlayed'], PA=s['plateAppearances'], AB=s['atBats'], H=s['hits'], R=s['runs'],
                D=s['doubles'], T=s['triples'], HR=s['homeRuns'], RBI=s['rbi'], SB=s['stolenBases'],
                BB=s['baseOnBalls'], HBP=s.get('hitByPitch', 0), SF=s.get('sacFlies', 0), TB=s['totalBases'])


def pcounts(s, qs):
    return dict(G=s['gamesPlayed'], GS=s['gamesStarted'], IP=ip(s['inningsPitched']), W=s['wins'],
                L=s['losses'], CG=s['completeGames'], SV=s['saves'], HLD=s['holds'], K=s['strikeOuts'],
                ER=s['earnedRuns'], HA=s['hits'], BBA=s['baseOnBalls'], QS=qs)


def hitter_week(c, per_week=None):
    f = 1 / per_week if per_week else G_WEEK / c['G']
    return {'H': c['H'] * f, 'AB': c['AB'] * f, 'R': c['R'] * f, '3B': c['T'] * f, 'HR': c['HR'] * f,
            'RBI': c['RBI'] * f, 'SB': c['SB'] * f, 'BB': c['BB'] * f, 'XBH': (c['D'] + c['T'] + c['HR']) * f,
            'TB': c['TB'] * f, 'OB': (c['H'] + c['BB'] + c['HBP']) * f,
            'PAO': (c['AB'] + c['BB'] + c['HBP'] + c['SF']) * f}


def pitcher_week(c, role, per_week=None):
    if per_week:
        f = 1 / per_week
    elif role == 'SP':
        f = SP_WEEK / (c['GS'] + 0.25 * (c['G'] - c['GS']))   # relief outings count as a quarter start
    else:
        ipg = c['IP'] / c['G']
        f = min(RP_WEEK, RP_IP_WEEK / max(ipg, 1e-9)) / c['G']
    return {'IP': c['IP'] * f, 'W': c['W'] * f, 'L': c['L'] * f, 'CG': c['CG'] * f, 'SV': c['SV'] * f,
            'K': c['K'] * f, 'HLD': c['HLD'] * f, 'ER': c['ER'] * f, 'BR': (c['HA'] + c['BBA']) * f,
            'BBP': c['BBA'] * f, 'QS': c['QS'] * f}


def swap(avg, repl, add):
    c = dict(avg)
    for k in add: c[k] = c[k] - repl.get(k, 0) + add[k]
    return c


def repl_line(lines, band):
    sel = lines[band[0]:band[1]]
    keys = sel[0].keys()
    return {k: float(np.mean([l[k] for l in sel])) for k in keys}


def build(win='2026_season', fallback='2025_2h', min_pa=60, min_gs=3, min_rp=10, season_weeks=None, min_raw=None):
    """season_weeks: if set, season-total mode (totals / weeks, no regression), like Yahoo."""
    avg, opp, nweeks = baseline()
    base_cw, base_win, base_per = score(avg, opp)

    # Yahoo ranks and QS (2026 season pull)
    yb = yahoo('season_B'); yp = yahoo('season_P')
    yrank = {}
    for i, r in enumerate(yb): yrank.setdefault(('H', norm(r['n'])), (i + 1, r))
    for i, r in enumerate(yp): yrank.setdefault(('P', norm(r['n'])), (i + 1, r))

    # QS rate model for pitchers without a Yahoo QS number: fit on matched SPs
    sp26 = [x for x in mlb_rows('2026_season', 'pitching') if x['stat']['gamesStarted'] >= 8]
    X, Y = [], []
    for x in sp26:
        s = x['stat']; m = yrank.get(('P', norm(x['player']['fullName'])))
        if not m or '83' not in m[1].get('s', {}): continue
        gs = s['gamesStarted']
        X.append([1, ip(s['inningsPitched']) / gs, float(s['era'])]); Y.append(float(m[1]['s']['83']) / gs)
    beta = np.linalg.lstsq(np.array(X), np.array(Y), rcond=None)[0]

    def qs_rate(s, name, actual):
        gs = s['gamesStarted']
        if actual:
            m = yrank.get(('P', norm(name)))
            if m and m[1].get('s', {}).get('83') not in (None, '', '-'):
                return float(m[1]['s']['83']) / gs
        ipx = ip(s['inningsPitched'])
        era = 9 * s['earnedRuns'] / ipx if ipx else 9.0
        v = beta @ [1, ipx / gs, era]
        return float(min(max(v, 0), 0.9))

    def gather(w):
        out = {}
        for x in mlb_rows(w, 'hitting'):
            if x['position']['abbreviation'] == 'P': continue
            out[('H', x['player']['id'])] = (x, hcounts(x['stat']))
        for x in mlb_rows(w, 'pitching'):
            st = x['stat']
            actual = win == '2026_season' and w == win
            q = qs_rate(st, x['player']['fullName'], actual) * st['gamesStarted'] if st['gamesStarted'] else 0
            out[('P', x['player']['id'])] = (x, pcounts(st, q))
        return out

    main = gather(win)
    fb = gather(fallback) if fallback else {}
    comb = {}
    for key, (x, c) in main.items():
        c = dict(c)
        if key in fb:
            for k, v in fb[key][1].items(): c[k] = c[k] + W_PRIOR * v
        comb[key] = (x, c)

    # role averages (per PA / per start / per appearance) for regression
    def role_of(key, c):
        if key[0] == 'H': return 'H'
        return 'SP' if c['GS'] >= 0.5 * c['G'] else 'RP'
    pools = {'H': [], 'SP': [], 'RP': []}
    for key, (x, c) in comb.items():
        r = role_of(key, c)
        pools[r].append(c)
    # regulars only: at least half the volume of the busiest player in the role
    for r, u in (('H', 'PA'), ('SP', 'GS'), ('RP', 'G')):
        top = max(c[u] for c in pools[r])
        pools[r] = [c for c in pools[r] if c[u] >= 0.5 * top]
    avgline = {}
    for r, cs in pools.items():
        unit = PRIOR[r][0]
        tot = {k: sum(c[k] for c in cs) for k in cs[0]}
        avgline[r] = {k: v / tot[unit] for k, v in tot.items()}   # per one unit

    players = []
    for key, (x, c) in comb.items():
        r = role_of(key, c)
        unit, k0 = PRIOR[r]
        if min_raw:
            s1 = x['stat']
            have = {'H': s1.get('plateAppearances', 0), 'SP': s1.get('gamesStarted', 0), 'RP': s1.get('gamesPlayed', 0)}[r]
            if have < min_raw[r]: continue
        if r == 'H' and c['PA'] < min_pa: continue
        if r == 'SP' and c['GS'] < min_gs: continue
        if r == 'RP' and c['G'] < min_rp: continue
        reg = c if season_weeks else {k: c[k] + k0 * avgline[r][k] for k in c}
        line = hitter_week(reg, season_weeks) if r == 'H' else pitcher_week(reg, r, season_weeks)
        s0 = x['stat']
        players.append({'id': x['player']['id'], 'name': x['player']['fullName'], 'team': x['team'].get('id'),
                        'role': r, 'pos': x['position']['abbreviation'] if r == 'H' else r,
                        'G': s0['gamesPlayed'], 'PA': s0.get('plateAppearances'), 'GS': s0.get('gamesStarted'),
                        'IP': ip(s0['inningsPitched']) if r != 'H' else None, 'line': line, 'raw': s0})

    # replacement level: iterate (start from the median line of each role)
    repl = {}
    for role in N_REPL:
        ls = [p['line'] for p in players if p['role'] == role]
        repl[role] = {k: float(np.median([l[k] for l in ls])) for k in ls[0]}
    for _ in range(3):
        for p in players:
            cw, wp, per = score(swap(avg, repl[p['role']], p['line']), opp)
            p['cw'], p['wp'], p['per'] = cw, wp, per
        for role, band in N_REPL.items():
            ls = sorted([p for p in players if p['role'] == role], key=lambda p: -p['wp'])
            repl[role] = repl_line([p['line'] for p in ls], band)
    # final pass vs final replacement
    rbase = {}
    for role in N_REPL:
        rbase[role] = score(swap(avg, repl[role], repl[role]), opp)
    for p in players:
        cw, wp, per = score(swap(avg, repl[p['role']], p['line']), opp)
        b = rbase[p['role']]
        p['cw'], p['wp'] = cw - b[0], wp - b[1]
        p['per'] = {k: per[k] - b[2][k] for k in CATS}
        side = 'H' if p['role'] == 'H' else 'P'
        m = yrank.get((side, norm(p['name'])))
        p['yahoo'] = m[0] if m else None
        p['ytm'] = m[1]['tm'] if m else None
        p['ypos'] = m[1]['pos'] if m else None
    players.sort(key=lambda p: -p['wp'])
    for i, p in enumerate(players): p['rank'] = i + 1
    return players, dict(avg=avg, base_cw=base_cw, base_win=base_win, weeks=nweeks, repl=repl)


if __name__ == '__main__':
    pl, meta = build()
    print('weeks', meta['weeks'], 'baseline cat wins', round(meta['base_cw'], 2), 'win%', round(meta['base_win'], 3))
    for p in pl[:40]:
        print(f"{p['rank']:3d} {p['name'][:22]:22s} {p['role']:2s} +cat {p['cw']:.3f}  +win% {100*p['wp']:.2f}  yahoo {p['yahoo']}")
