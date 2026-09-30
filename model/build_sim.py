"""Roster-shape simulator: daily lineups under Frank Cup slot rules, scored vs 810 real opponent weeks."""
import numpy as np, sys
from model import build, baseline, score, CATS, SP_WEEK, RP_WEEK, G_WEEK
rng = np.random.default_rng(7)

players, meta = build('2026_season', '2025_2h', min_raw={'H': 150, 'SP': 8, 'RP': 20})
avg, opp, _ = baseline()
KEYS = ['H', 'AB', 'R', '3B', 'HR', 'RBI', 'SB', 'BB', 'XBH', 'TB', 'OB', 'PAO',
        'IP', 'W', 'L', 'CG', 'SV', 'K', 'HLD', 'ER', 'BR', 'BBP', 'QS']

def unit(p):
    """per game (H), per start (SP), per appearance (RP) line, as a vector over KEYS"""
    if p['role'] == 'H': d = G_WEEK
    elif p['role'] == 'SP': d = SP_WEEK
    else:
        s = p['raw']; ipg = p['IP'] / max(s['gamesPlayed'], 1)
        d = min(RP_WEEK, 3.5 / max(ipg, 1e-9))
    return np.array([p['line'].get(k, 0.0) / d for k in KEYS])

pool = {r: sorted([p for p in players if p['role'] == r], key=lambda p: -p['wp']) for r in ('H', 'SP', 'RP')}

def tier(role, k, teams=10):
    """a typical team's k-th best player at a role (k from 1): avg of ranks 10(k-1)..10k-1"""
    grp = pool[role][teams * (k - 1): teams * k]
    return np.mean([unit(p) for p in grp], axis=0)

P_HIT = 0.82          # chance a regular hitter plays on a given day
P_START = SP_WEEK / 7 # chance a rotation SP starts on a given day
P_APP = RP_WEEK / 7
BENCH_FIT = 0.7      # chance a bench bat is eligible for the open slot (C/SS gaps are hard to fill)
CAL = {}             # multipliers so the league-typical shape matches the real average team's ratios   # chance a reliever pitches on a given day (if active)

def week(nh, nsp, nrp, sims=600, elite_rp=0):
    H = [tier('H', k) for k in range(1, nh + 1)]
    SP = [tier('SP', k) for k in range(1, nsp + 1)]
    # elite_rp: take relievers from the top of the pool (as if you grabbed the highly ranked ones)
    RP = [tier('RP', k) for k in range(1, nrp + 1)]
    out = []
    for _ in range(sims):
        tot = np.zeros(len(KEYS))
        for day in range(7):
            plays = [h for h in H[:10] if rng.random() < P_HIT]      # starters who play today
            for h in H[10:]:                                          # bench bats fill open slots if eligible
                if len(plays) < 10 and rng.random() < P_HIT and rng.random() < BENCH_FIT: plays.append(h)
            for h in plays: tot += h
            starts = [s for s in SP if rng.random() < P_START][:7]    # SP + P slots
            for s in starts: tot += s
            rp_slots = 2 + max(0, 4 - max(0, len(starts) - 3))
            for r in RP[:rp_slots]:
                if rng.random() < P_APP: tot += r
        out.append(tot)
    out = np.array(out)
    for k, f in CAL.items(): out[:, KEYS.index(k)] *= f
    return out

def calibrate(shape=(10, 12, 2)):
    CAL.clear()
    m = week(*shape, sims=1500).mean(axis=0); g = dict(zip(KEYS, m))
    CAL['ER'] = (avg['ER'] / avg['IP']) / (g['ER'] / g['IP'])
    CAL['BR'] = (avg['BR'] / avg['IP']) / (g['BR'] / g['IP'])
    CAL['H'] = (avg['H'] / avg['AB']) / (g['H'] / g['AB'])
    CAL['TB'] = (avg['TB'] / avg['AB']) / (g['TB'] / g['AB'])
    CAL['OB'] = (avg['OB'] / avg['PAO']) / (g['OB'] / g['PAO'])
    return dict(CAL)

def evaluate(nh, nsp, nrp, sims=600):
    wk = week(nh, nsp, nrp, sims)
    cws, wps = [], []
    for t in wk:
        c = dict(zip(KEYS, t)); c['A'] = avg['A']; c['E'] = avg['E']
        cw, wp, per = score(c, opp)
        if c['IP'] < 20:   # under the 20 IP minimum: ERA, WHIP, K/BB treated as losses
            cw -= per['ERA'] + per['WHIP'] + per['KBB']; wp = float(np.clip(cw - 10.5, 0, 1))
        cws.append(cw); wps.append(wp)
    return np.mean(cws), np.mean(wps), wk.mean(axis=0)

if __name__ == '__main__':
    # calibration: league-typical shape vs the real average team week
    cw, wp, m = evaluate(10, 12, 2)
    print('typical 10H/12SP/2RP  sim:', {k: round(v, 1) for k, v in zip(KEYS, m) if k in ('AB','R','HR','IP','K','W','QS','SV','HLD')})
    print('                     real:', {k: round(avg[k], 1) for k in ('AB','R','HR','IP','K','W','QS','SV','HLD')})
