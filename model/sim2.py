"""
Realistic roster-shape simulator for The Frank Cup.

Per simulated week:
- Every rostered player is a real player drawn from the talent tier a team at that
  depth would own (tier k = ranks T*(k-1) .. T*k-1 by per-game value, T = teams).
- MLB schedule: each player's team is off with prob 35% Mon/Thu, 2% other days
  (~6.2 games/week). Regular hitters rest 7% of team games.
- SP on a 5-man rotation: starts every 5th team game from a random phase, and a
  scheduled start is skipped with prob SKIP (calibrated).
- RP pitch in 40% of team games (~2.5/week), only if in an active slot.
- Injuries: a player is out for the week with prob INJ[role].
- Adds (4/week): first replace injured starters with free-agent-level players,
  then stream starts (FA-level SP) through the stream spots (<= 2 starts per spot).
- Daily lineup: hitters fill C,1B,2B,3B,SS,OF,OF,OF,Util,Util by eligibility,
  best first (max matching). SP with a start fill SP then P slots; RP fill RP then
  leftover P slots.
"""
import numpy as np, json, glob, sys
from model import build, baseline, score, CATS, SP_WEEK, RP_WEEK, G_WEEK, RP_IP_WEEK
rng = np.random.default_rng(11)

KEYS = ['H', 'AB', 'R', '3B', 'HR', 'RBI', 'SB', 'BB', 'XBH', 'TB', 'OB', 'PAO',
        'IP', 'W', 'L', 'CG', 'SV', 'K', 'HLD', 'ER', 'BR', 'BBP', 'QS']
KI = {k: i for i, k in enumerate(KEYS)}
OFF = [0.35, 0.02, 0.02, 0.35, 0.02, 0.02, 0.02]   # Mon..Sun team off-day chance
REST = 0.0   # calibrated: rest days already sit inside per-game rates
P_APP = 0.40
INJ = {'H': 0.06, 'SP': 0.08, 'RP': 0.06}
SKIP = 0.10
BENCH_OK_FA = True

RULES = {
    2026: dict(teams=10, hslots=['C', '1B', '2B', '3B', 'SS', 'OF', 'OF', 'OF', 'Util', 'Util'],
               sp=3, rp=2, p=4, bench=5),
    2027: dict(teams=12, hslots=['C', '1B', '2B', '3B', 'SS', 'OF', 'OF', 'OF', 'Util', 'Util'],
               sp=3, rp=2, p=3, bench=3),
}

players, meta = build('2026_season', '2025_2h', min_raw={'H': 150, 'SP': 8, 'RP': 20})
avg, opp_real, _ = baseline()


def unit(p):
    if p['role'] == 'H': d = G_WEEK
    elif p['role'] == 'SP': d = SP_WEEK
    else:
        ipg = p['IP'] / max(p['raw']['gamesPlayed'], 1)
        d = min(RP_WEEK, RP_IP_WEEK / max(ipg, 1e-9))
    return np.array([p['line'].get(k, 0.0) / d for k in KEYS])


def elig(p):
    pos = (p.get('ypos') or p.get('pos') or 'Util').split(',')
    s = set()
    for x in pos:
        x = x.strip()
        if x in ('LF', 'CF', 'RF'): x = 'OF'
        s.add(x)
    s.add('Util')
    return s


POOL = {}
for r in ('H', 'SP', 'RP'):
    ps = sorted([p for p in players if p['role'] == r], key=lambda p: -p['wp'])
    POOL[r] = [dict(u=unit(p), el=elig(p) if r == 'H' else None, name=p['name']) for p in ps]


def draw(role, lo, hi):
    grp = POOL[role][lo:hi] or POOL[role][-20:]
    return grp[rng.integers(len(grp))]


def fill_hitters(avail, slots):
    """max matching of playing hitters (sorted best first) to slots; returns placed list"""
    match = [None] * len(slots)
    def try_place(h, seen):
        for j, s in enumerate(slots):
            if s in h['el'] and j not in seen:
                seen.add(j)
                if match[j] is None or try_place(match[j], seen):
                    match[j] = h; return True
        return False
    for h in avail:
        try_place(h, set())
    return [m for m in match if m is not None]


class League:
    def __init__(self, year, typical):
        self.R = RULES[year]; self.T = self.R['teams']
        self.typical = typical    # (H, SP, RP, S) most teams run; sets what's left for free agents
        nH, nSP, nRP, nS = typical
        self.fa = {'H': self.T * nH, 'SP': self.T * (nSP + nS), 'RP': self.T * nRP}

    def roster(self, nH, nSP, nRP):
        T = self.T
        H = [draw('H', T * k, T * (k + 1)) for k in range(nH)]
        SP = [draw('SP', T * k, T * (k + 1)) for k in range(nSP)]
        RP = [draw('RP', T * k, T * (k + 1)) for k in range(nRP)]
        H.sort(key=lambda h: -h['u'].sum());
        return H, SP, RP

    def fa_player(self, role):
        lo = self.fa[role]; return draw(role, lo, lo + 25)

    def week(self, shape):
        nH, nSP, nRP, nS = shape
        R = self.R
        H, SP, RP = self.roster(nH, nSP, nRP)
        adds = 4
        tot = np.zeros(len(KEYS))
        # injuries for the week
        H_ok = [h for h in H if rng.random() >= INJ['H']]
        SP_ok = [s for s in SP if rng.random() >= INJ['SP']]
        RP_ok = [r for r in RP if rng.random() >= INJ['RP']]
        # replace injured starters (only if it leaves a starting hole) using adds
        while len(H_ok) < len(R['hslots']) and adds > 0 and len(H_ok) < len(H):
            H_ok.append(self.fa_player('H')); adds -= 1
        need_sp = min(len(SP), R['sp'] + R['p']) - len(SP_ok)
        while need_sp > 0 and adds > 0:
            SP_ok.append(self.fa_player('SP')); adds -= 1; need_sp -= 1
        stream_starts = min(adds, 2 * nS)
        # each player: MLB team off-days, rotation phase
        def sched():
            return [rng.random() >= OFF[d] for d in range(7)]
        hs = [(h, sched()) for h in H_ok]
        sps = []
        for s in SP_ok:
            sc = sched(); phase = rng.integers(5); g = 0; days = []
            for d in range(7):
                if sc[d]:
                    if (g + phase) % 5 == 0 and rng.random() >= SKIP: days.append(d)
                    g += 1
            sps.append((s, set(days)))
        rps = [(r, sched()) for r in RP_ok]
        stream_days = set(rng.choice(7, size=stream_starts, replace=False)) if stream_starts else set()
        ip = 0.0
        for d in range(7):
            playing = [h for h, sc in hs if sc[d] and rng.random() >= REST]
            for h in fill_hitters(playing, R['hslots']): tot += h['u']
            starters = [s for s, days in sps if d in days]
            if d in stream_days: starters.append(self.fa_player('SP'))
            starters = starters[:R['sp'] + R['p']]
            for s in starters: tot += s['u']
            left_p = R['p'] - max(0, len(starters) - R['sp'])
            n_active = R['rp'] + max(0, left_p)
            for i, (r, sc) in enumerate(rps):
                if i < n_active and sc[d] and rng.random() < P_APP: tot += r['u']
        return tot


CAL = {}


def apply_cal(t):
    t = t.copy()
    for k, f in CAL.items(): t[KI[k]] *= f
    return t


NOISE = {'hit': 0.08, 'pit': 0.10}   # weekly hot/cold swing (sd), tuned so spreads match real weeks
HIT_CNT = ['H', 'R', '3B', 'HR', 'RBI', 'SB', 'BB', 'XBH']
PIT_CNT = ['W', 'L', 'CG', 'SV', 'HLD', 'K', 'QS']


def noisy(t):
    """expected week -> one realized week: shared hot/cold factor + game-level randomness"""
    t = t.copy()
    mh = max(0.5, rng.normal(1, NOISE['hit'])); mp = max(0.5, rng.normal(1, NOISE['pit']))
    exp_h, exp_tb, exp_ob, exp_bb = t[KI['H']], t[KI['TB']], t[KI['OB']], t[KI['BB']]
    exp_hbp = max(exp_ob - exp_h - exp_bb, 0)
    for k in HIT_CNT:
        if k == 'H': continue
        t[KI[k]] = rng.poisson(max(t[KI[k]] * mh, 0))
    ab = max(int(round(t[KI['AB']])), 1)
    t[KI['AB']] = ab
    t[KI['H']] = rng.binomial(ab, min(0.6, exp_h / max(t[KI['AB']], 1) * (1 + (mh - 1) * 0.3)))
    h = t[KI['H']]
    extra = max(exp_tb - exp_h, 0) * (h / exp_h if exp_h else 1)          # extra bases scale with hits
    t[KI['TB']] = h + max(0.0, rng.normal(extra, np.sqrt(max(extra, 0.1)) * 1.5))
    t[KI['OB']] = h + t[KI['BB']] + rng.poisson(exp_hbp)
    for k in PIT_CNT:
        t[KI[k]] = rng.poisson(max(t[KI[k]], 0))
    er = max(t[KI['ER']] * mp, 0.1)
    t[KI['ER']] = rng.negative_binomial(er, 0.5)                           # mean er, variance 2x (runs cluster)
    br = t[KI['BR']] * mp
    t[KI['BR']] = max(0.0, rng.normal(br, np.sqrt(max(br, 1)) * 0.8))
    t[KI['BBP']] = rng.poisson(max(t[KI['BBP']], 0))
    return t


def weeks(lg, shape, n):
    return np.array([noisy(apply_cal(lg.week(shape))) for _ in range(n)])


def weeks_exp(lg, shape, n):
    return np.array([apply_cal(lg.week(shape)) for _ in range(n)])


def calibrate(lg, shape, n=3000):
    """match the league-typical shape to the real average team week"""
    global SKIP
    CAL.clear()
    # innings: tune rotation skip rate
    for _ in range(3):
        m = weeks(lg, shape, n).mean(axis=0)
        ratio = avg['IP'] / m[KI['IP']]
        SKIP = float(np.clip(1 - (1 - SKIP) * ratio, 0, 0.6))
    m = weeks(lg, shape, n).mean(axis=0); g = dict(zip(KEYS, m))
    CAL.update({'ER': (avg['ER'] / avg['IP']) / (g['ER'] / g['IP']), 'BR': (avg['BR'] / avg['IP']) / (g['BR'] / g['IP']),
                'H': (avg['H'] / avg['AB']) / (g['H'] / g['AB']), 'TB': (avg['TB'] / avg['AB']) / (g['TB'] / g['AB']),
                'OB': (avg['OB'] / avg['PAO']) / (g['OB'] / g['PAO'])})
    return SKIP, dict(CAL), g


def to_opp(wk):
    """simulated weeks -> opponent arrays in display form (like baseline's opp)"""
    from model import displayed
    cols = {k: wk[:, KI[k]] for k in KEYS}
    cols['A'] = np.full(len(wk), avg['A']); cols['E'] = np.full(len(wk), avg['E'])
    d = displayed(cols)
    return {k: np.asarray(d[k], float) for k in CATS}


def evaluate(lg, shape, opp, n=1500):
    wk = weeks(lg, shape, n)
    wps, per_acc = [], {k: 0.0 for k in CATS}
    for t in wk:
        c = dict(zip(KEYS, t)); c['A'] = avg['A']; c['E'] = avg['E']
        cw, wp, per = score(c, opp)
        if c['IP'] < 20:
            cw -= per['ERA'] + per['WHIP'] + per['KBB']; wp = float(np.clip(cw - 10.5, 0, 1))
        wps.append(wp)
        for k in per: per_acc[k] += per[k] / n
    wps = np.array(wps)
    return wps.mean(), wps.std() / np.sqrt(n), per_acc, wk.mean(axis=0), wk.std(axis=0)
