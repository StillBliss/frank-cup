"""
2027 talent model (per game when he plays) + durability.

Talent: Marcel-style. MLB 2026/2025/2024 weighted 5/4/3 by playing time, plus
minor league stats (2026 weight 5, 2025 weight 4) translated to MLB level and
discounted, plus a pull toward average. Rookies get most of their line from the
minors; a veteran with a missing year just has less weight that year, never zeros.
Age: Marcel curve to age on 7/1/2027 (steeper for steals). Pedigree: small bump
for high MLB draft picks who are still young.

Durability: share of a healthy season he's expected to be available, from
injured-list days in MLB seasons since his debut (5/4/3), pulled toward average,
plus known long-term injuries carrying into 2027.
"""
import json, os, re, datetime as dt, collections
import numpy as np

H = '/home/claude/research/research_out/history'
SEASONS = {2026: 5, 2025: 4, 2024: 3}
DUR_W = {2026: 5, 2025: 4, 2024: 3, 2023: 2, 2022: 1}   # injury history reaches further back, older years count less
MILB_W = {2026: 5, 2025: 4}
MILB_DISC = 0.3            # a minor league PA counts as 0.3 of an MLB PA of information (back-tested)
LEVEL = {'AAA': 1.0, 'AA': 0.93, 'A+': 0.86}   # step-down on "good" rates vs AAA
PRIOR_PA, PRIOR_BF = 2000, 1700   # back-test: a stronger pull toward average cut 2026 error
AGE_DATE = dt.date(2027, 7, 1)
AGE_ON = True            # switches used by the back-test
OUT_PRIOR_SP, OUT_PRIOR_RP, PAG_PRIOR = 30, 40, 60   # pulls on innings per outing, decisions per outing, PA per game
FIELD_PRIOR_A, FIELD_PRIOR_E = 100, 600               # pull on assists / errors per game toward his position's average
PEDIGREE_ON = True
SEASON_27 = (dt.date(2027, 3, 25), dt.date(2027, 9, 26))

# AAA -> MLB translation (measured on 2025-26 pairs)
HT = {'H': .88, 'D': .84, 'T': .67, 'HR': .73, 'R': .74, 'RBI': .76, 'SB': .50, 'BB': .69, 'HBP': .8, 'SF': .8}
# pitchers: measured AAA pairs are survivor-biased (only the successful ones stick), so use harsher standard factors
PT = {'K': .84, 'BB': 1.06, 'HA': 1.07, 'ER': 1.22, 'HR': 1.35}
MILB_DISC_P = 0.4
LEVEL_P = {'AAA': 1.0, 'AA': 0.88, 'A+': 0.78}


def load(f):
    return json.load(open(f))


def rows(f):
    return {x['player']['id']: (x['stat'], x) for x in load(f)['stats'][0]['splits']}


def ipf(v):
    a, _, b = str(v).partition('.'); return int(a) + int(b or 0) / 3


people = {int(k): v for k, v in load(f'{H}/people.json').items()}


def age(pid):
    b = (people.get(pid) or {}).get('birth')
    if not b: return 28.0
    b = dt.date.fromisoformat(b)
    return (AGE_DATE - b).days / 365.25


# ------------------------------------------------------------------ hitters
HCOLS = ['PA', 'AB', 'H', 'D', 'T', 'HR', 'R', 'RBI', 'SB', 'BB', 'HBP', 'SF', 'G']


def hcnt(s):
    return dict(PA=s['plateAppearances'], AB=s['atBats'], H=s['hits'], D=s['doubles'], T=s['triples'], HR=s['homeRuns'],
                R=s['runs'], RBI=s['rbi'], SB=s['stolenBases'], BB=s['baseOnBalls'], HBP=s.get('hitByPitch', 0),
                SF=s.get('sacFlies', 0), G=s['gamesPlayed'])


def pcnt(s):
    return dict(BF=s['battersFaced'], IP=ipf(s['inningsPitched']), G=s['gamesPlayed'], GS=s['gamesStarted'],
                W=s['wins'], L=s['losses'], CG=s['completeGames'], SV=s['saves'], HLD=s['holds'], K=s['strikeOuts'],
                BB=s['baseOnBalls'], HA=s['hits'], ER=s['earnedRuns'], HR=s['homeRuns'])


def build():
    mlb_h = {y: rows(f'{H}/seasons/{y}_hitting.json') for y in SEASONS}
    mlb_p = {y: rows(f'{H}/seasons/{y}_pitching.json') for y in SEASONS}
    Y0 = max(SEASONS)
    milb_h = {(y, l): rows(f'{H}/milb/{y}_{l}_hitting.json') for y in MILB_W for l in LEVEL if os.path.exists(f'{H}/milb/{y}_{l}_hitting.json')}
    milb_p = {(y, l): rows(f'{H}/milb/{y}_{l}_pitching.json') for y in MILB_W for l in LEVEL if os.path.exists(f'{H}/milb/{y}_{l}_pitching.json')}

    # league-average MLB rates (2024-26 regulars) for the pull toward average
    def lg(rowsets, cnt, unit, pick):
        tot = collections.Counter()
        for rs in rowsets:
            for pid, (s, x) in rs.items():
                c = cnt(s)
                if pick(c): tot.update(c)
        return {k: v / tot[unit] for k, v in tot.items()}
    LG_H = lg(mlb_h.values(), hcnt, 'PA', lambda c: c['PA'] >= 1)
    LG_SP = lg(mlb_p.values(), pcnt, 'BF', lambda c: c['GS'] >= 0.5 * c['G'] and c['BF'] >= 1)
    LG_RP = lg(mlb_p.values(), pcnt, 'BF', lambda c: c['GS'] < 0.5 * c['G'] and c['BF'] >= 1)

    out = {}
    # ---------------- hitters
    ids = set().union(*[set(r) for r in mlb_h.values()]) | set().union(*[set(r) for r in milb_h.values()])
    for pid in ids:
        acc = collections.Counter(); wpa = 0.0; mlb_pa = 0; name = None; team = None; pos = None
        for y, w in SEASONS.items():
            r = mlb_h[y].get(pid)
            if not r: continue
            s, x = r
            if x['position']['abbreviation'] == 'P': continue
            c = hcnt(s); mlb_pa += c['PA']; name = x['player']['fullName']; team = x['team'].get('id') if y == Y0 or team is None else team
            pos = x['position']['abbreviation']
            for k in HCOLS: acc[k] += w * c[k]
            wpa += w * c['PA']
        mi_pa = 0
        for (y, l), rs in milb_h.items():
            r = rs.get(pid)
            if not r: continue
            s, x = r; c = hcnt(s)
            if c['PA'] < 30: continue
            name = name or x['player']['fullName']
            f = MILB_W[y] * MILB_DISC
            good = LEVEL[l]
            for k in HCOLS:
                v = c[k]
                if k in HT: v *= HT[k] * good
                acc[k] += f * v
            acc['AB'] += 0; mi_pa += c['PA']
        if not name or (mlb_pa < 50 and mi_pa < 150): continue
        P = PRIOR_PA
        rate = {k: (acc[k] + P * LG_H[k]) / (acc['PA'] + P) for k in HCOLS if k not in ('PA',)}
        a = age(pid)
        # Marcel age factor on the good rates; steals age faster
        fa = 1 + (29 - a) * (0.006 if a < 29 else 0.003)
        fsb = 1 + (26 - a) * 0.04
        if AGE_ON:
            for k in ('H', 'D', 'T', 'HR', 'R', 'RBI', 'BB'): rate[k] *= fa
            rate['SB'] *= max(0.3, fsb)
            rate['T'] *= max(0.4, 1 + (26 - a) * 0.03)
        # pedigree: recent high draft pick, still young
        p = people.get(pid) or {}
        if PEDIGREE_ON and p.get('draft_round') in ('1', 1) and a < 26 and mlb_pa < 800:
            bump = 1.03 if (p.get('draft_pick') or 99) <= 15 else 1.015
            for k in ('H', 'D', 'HR', 'BB', 'R', 'RBI'): rate[k] *= bump
        # PA per game: his own MLB rate, pulled toward a regular's 4.1
        g = sum(w * (mlb_h[y][pid][0]['gamesPlayed'] if pid in mlb_h[y] else 0) for y, w in SEASONS.items())
        pa_g = (wpa + 4.1 * PAG_PRIOR) / (g + PAG_PRIOR) if g else 3.9
        rate['PA'] = 1.0
        top = max([l for (yy, l), rs in milb_h.items() if yy == Y0 and pid in rs and rs[pid][0]['plateAppearances'] >= 100] or ['none'], key=lambda l: {'AAA': 3, 'AA': 2, 'A+': 1, 'none': 0}[l])
        pa26 = mlb_h[Y0][pid][0]['plateAppearances'] if pid in mlb_h[Y0] else 0
        share = 1.0 if pa26 >= 250 or mlb_pa >= 600 else max({'AAA': .45, 'AA': .2, 'A+': .05, 'none': .5}[top], .7 if pa26 >= 100 else 0)
        out[('H', pid)] = dict(pa_y0=pa26, g_y0=(mlb_h[Y0][pid][0]['gamesPlayed'] if pid in mlb_h[Y0] else 0), mlb_share=share, top_level=top, id=pid, name=name, role='H', pos=pos, team=team, age=round(a, 1), mlb_pa=mlb_pa, milb_pa=mi_pa,
                               rate=rate, pa_g=pa_g, rookie=mlb_pa < 300)

    # ---------------- pitchers
    ids = set().union(*[set(r) for r in mlb_p.values()]) | set().union(*[set(r) for r in milb_p.values()])
    PC = ['BF', 'IP', 'G', 'GS', 'W', 'L', 'CG', 'SV', 'HLD', 'K', 'BB', 'HA', 'ER', 'HR']
    for pid in ids:
        acc = collections.Counter(); mlb_bf = 0; name = None; team = None; gs_share = []
        for y, w in SEASONS.items():
            r = mlb_p[y].get(pid)
            if not r: continue
            s, x = r; c = pcnt(s); mlb_bf += c['BF']; name = x['player']['fullName']
            team = x['team'].get('id') if y == Y0 or team is None else team
            for k in PC: acc[k] += w * c[k]
            gs_share.append((w * c['G'], c['GS'] / max(c['G'], 1)))
        mi_bf = 0
        for (y, l), rs in milb_p.items():
            r = rs.get(pid)
            if not r: continue
            s, x = r; c = pcnt(s)
            if c['BF'] < 30: continue
            name = name or x['player']['fullName']
            f = MILB_W[y] * MILB_DISC_P; step = 1 / LEVEL_P[l]
            for k in PC:
                v = c[k]
                if k == 'K': v *= PT['K'] / step
                elif k in PT: v *= PT[k] * step
                if k in ('W', 'L', 'SV', 'HLD', 'CG'): continue   # minor league decisions don't carry
                acc[k] += f * v
            mi_bf += c['BF']; gs_share.append((f * c['G'], c['GS'] / max(c['G'], 1)))
        if not name or (mlb_bf < 50 and mi_bf < 150): continue
        tot_w = sum(w for w, _ in gs_share) or 1
        sp = sum(w * s for w, s in gs_share) / tot_w >= 0.5
        L = LG_SP if sp else LG_RP
        P = PRIOR_BF
        rate = {k: (acc[k] + P * L[k]) / (acc['BF'] + P) for k in ('K', 'BB', 'HA', 'ER', 'HR', 'IP')}
        a = age(pid)
        fa = 1 + (28 - a) * (0.006 if a < 28 else 0.004) - max(0.0, a - 33) * 0.012   # >1 = better; pitchers fade faster past 33
        if AGE_ON:
            rate['K'] *= fa
            for k in ('BB', 'HA', 'ER', 'HR'): rate[k] /= fa
        # workload per outing and decisions per outing (MLB only; minors don't transfer)
        g = acc['G'] if acc['G'] else 1
        if sp:
            gs = max(acc['GS'], 1)
            ip_out = (acc['IP'] + 5.3 * OUT_PRIOR_SP) / (gs + OUT_PRIOR_SP) if acc['GS'] else 5.0
            per = {k: (acc[k] + OUT_PRIOR_SP * (L[k] / L['GS'] if L['GS'] else 0)) / (gs + OUT_PRIOR_SP) for k in ('W', 'L', 'CG')}
            per['SV'] = per['HLD'] = 0.0
        else:
            ip_out = (acc['IP'] + 1.0 * OUT_PRIOR_RP) / (g + OUT_PRIOR_RP) if acc['G'] else 1.0
            per = {k: (acc[k] + OUT_PRIOR_RP * (L[k] / L['G'])) / (g + OUT_PRIOR_RP) for k in ('W', 'L', 'SV', 'HLD')}
            per['CG'] = 0.0
        bf_out = ip_out / rate['IP']
        top = max([l for (yy, l), rs in milb_p.items() if yy == Y0 and pid in rs and rs[pid][0]['battersFaced'] >= 100] or ['none'], key=lambda l: {'AAA': 3, 'AA': 2, 'A+': 1, 'none': 0}[l])
        bf26 = mlb_p[Y0][pid][0]['battersFaced'] if pid in mlb_p[Y0] else 0
        share = 1.0 if bf26 >= 150 or mlb_bf >= 500 else max({'AAA': .45, 'AA': .2, 'A+': .05, 'none': .5}[top], .7 if bf26 >= 60 else 0)
        out[('P', pid)] = dict(g_y0=(mlb_p[Y0][pid][0]['gamesPlayed'] if pid in mlb_p[Y0] else 0), gs_y0=(mlb_p[Y0][pid][0]['gamesStarted'] if pid in mlb_p[Y0] else 0), mlb_share=share, top_level=top, id=pid, name=name, role='SP' if sp else 'RP', pos='SP' if sp else 'RP', team=team,
                               age=round(a, 1), mlb_bf=mlb_bf, milb_bf=mi_bf, rate=rate, ip_out=ip_out, bf_out=bf_out,
                               dec=per, rookie=mlb_bf < 250)
    return out, dict(LG_H=LG_H, LG_SP=LG_SP, LG_RP=LG_RP)


# ------------------------------------------------------------------ durability
LONG = re.compile(r'tommy john|ucl|ulnar collateral|labrum|acl|achilles|internal brace', re.I)


def il_days():
    days = collections.defaultdict(lambda: collections.Counter())
    open_ = {}
    long_term = {}
    for y in range(2022, 2027):
        ev = sorted(load(f'{H}/il/{y}.json'), key=lambda t: t['date'])
        s0, s1 = dt.date(y, 3, 26), dt.date(y, 9, 28)
        for t in ev:
            d = dt.date.fromisoformat(t['date'][:10]); desc = t['desc'].lower(); pid = t['id']
            if 'placed' in desc:
                m = re.search(r'retroactive to ([a-z]+ \d+, \d{4})', desc)
                if m:
                    try: d = dt.datetime.strptime(m.group(1).title(), '%B %d, %Y').date()
                    except ValueError: pass
                open_[pid] = d
                if (LONG.search(t['desc']) and ('surgery' in desc or 'repair' in desc or 'reconstruction' in desc)
                        and 'recover' not in desc):
                    long_term[pid] = (d, t['desc'])
            elif ('activated' in desc or 'reinstated' in desc) and pid in open_:
                long_term.pop(pid, None)          # he came back: no carry-over
                a, b = max(open_.pop(pid), s0), min(d, s1)
                if b > a: days[pid][a.year] += (b - a).days
        for pid, a in list(open_.items()):   # still out at season end
            a = max(a, s0)
            if a < s1: days[pid][y] += (s1 - a).days
            open_[pid] = dt.date(y + 1, 3, 26) if a <= s1 else a
    return days, long_term


def active_days():
    """days he was clearly on the field each season, from games played (so a stuck IL record can't claim them)"""
    out = collections.defaultdict(dict)
    for y in DUR_W:
        for pid, (s, x) in rows(f'{H}/seasons/{y}_hitting.json').items():
            if x['position']['abbreviation'] != 'P': out[('H', pid)][y] = min(186, s['gamesPlayed'] * 186 / 162)
        for pid, (s, x) in rows(f'{H}/seasons/{y}_pitching.json').items():
            gs, g = s['gamesStarted'], s['gamesPlayed']
            out[('P', pid)][y] = min(186, gs * 5.6 + (g - gs) * 2.6)
    return out


def durability(T):
    days, long_term = il_days()
    act = active_days()
    for key, p in T.items():
        a = act.get((key[0], p['id']), {})
        for y in DUR_W:
            if days[p['id']][y]:
                days[p['id']][y] = int(min(days[p['id']][y], max(0, 186 - a.get(y, 0))))
    season_len = 186.0
    out = {}
    lg = {'H': 0.10, 'SP': 0.18, 'RP': 0.14}      # typical share of season lost; refined below
    shares = collections.defaultdict(list)
    for key, p in T.items():
        pid = p['id']; deb = (people.get(pid) or {}).get('debut')
        debut_year = int(deb[:4]) if deb else 2099
        num = den = 0.0
        for y, w in DUR_W.items():
            if y < debut_year: continue        # not in the majors yet: not an injury
            f = min(1.0, days[pid][y] / season_len)
            num += w * f; den += w
        p['il_hist'] = {y: days[pid][y] for y in DUR_W if days[pid][y]}
        p['_num'], p['_den'] = num, den
        if den: shares[p['role']].append(num / den)
    for r in lg:
        if shares[r]: lg[r] = float(np.mean(shares[r]))
    for key, p in T.items():
        k0 = 8.0                               # prior strength, in weighted seasons
        miss = (p['_num'] + k0 * lg[p['role']]) / (p['_den'] + k0)
        miss *= 1 + max(0, p['age'] - 30) * 0.04 + (max(0, p['age'] - 33) * 0.04 if p['role'] != 'H' else 0)   # older players get hurt more, old pitchers most
        lt = long_term.get(p['id'])
        extra = 0.0
        if lt and lt[0] >= dt.date(2025, 10, 1):
            back = lt[0] + dt.timedelta(days=(420 if re.search(r'tommy john|ucl|ulnar|internal brace', lt[1], re.I) and p['role'] != 'H' else 270))
            s0, s1 = SEASON_27
            if back > s0: extra = min(1.0, (back - s0).days / (s1 - s0).days)
            p['long_term'] = lt[1].split('. ', 1)[-1] if '. ' in lt[1] else lt[1]
        p['avail'] = round(max(0.0, (1 - min(0.6, miss)) * (1 - extra)), 3)
        del p['_num'], p['_den']
    return lg


if __name__ == '__main__':
    T, LG = build()
    lg = durability(T)
    print(len(T), 'players', 'lg miss', lg)
    for n in ('Paul Skenes', 'Drew Rasmussen', 'Aaron Judge', 'Pete Crow-Armstrong', 'Jacob Misiorowski', 'Nick Kurtz', 'Konnor Griffin', 'Kevin McGonigle', 'Spencer Strider', 'Byron Buxton', 'Mike Trout'):
        for k, p in T.items():
            if p['name'] == n:
                r = p['rate']
                if p['role'] == 'H':
                    print(f"{n:20s} H age {p['age']} mlbPA {p['mlb_pa']} miPA {p['milb_pa']} avail {p['avail']} HR/600 {600*r['HR']:.0f} SB/600 {600*r['SB']:.0f} AVG {r['H']/r['AB']:.3f} {p.get('long_term','')}")
                else:
                    print(f"{n:20s} {p['role']} age {p['age']} mlbBF {p['mlb_bf']} avail {p['avail']} ERA {9*r['ER']/r['IP']:.2f} K/9 {9*r['K']/r['IP']:.1f} IP/out {p['ip_out']:.1f} {p.get('long_term','')}")


# ------------------------------------------------------------------ team context
def team_context(T):
    """Scale team-driven stats by the player's 2026 team: wins/losses for starters,
    save and hold chances for relievers, runs and RBI for hitters. Half strength,
    since his own history already carries some of his past teams."""
    import glob as _g
    nf = sorted(_g.glob('/home/claude/frank-cup/raw/2026/news/*.json'))[-1]
    st = json.load(open(nf))['standings']
    tm = {t['name']: t['id'] for t in load('/home/claude/research/research_out/mlb/teams.json')['teams']}
    wpct = {}
    for r in st:
        if r['team'] in tm: wpct[tm[r['team']]] = 0.5 + (r['w'] / max(1, r['w'] + r['l']) - 0.5) * 0.5   # regress halfway
    runs = collections.Counter(); games = collections.Counter()
    for pid, (s, x) in rows(f'{H}/seasons/2026_hitting.json').items():
        t = x['team'].get('id'); runs[t] += s['runs']
    lg_r = np.mean(list(runs.values()))
    off = {t: (runs[t] / lg_r) for t in runs}
    for p in T.values():
        t = p.get('team')
        if p['role'] == 'H':
            f = off.get(t, 1.0) ** 0.5
            p['rate']['R'] *= f; p['rate']['RBI'] *= f
            p['team_off'] = round(off.get(t, 1.0), 3)
        else:
            w = wpct.get(t, 0.5)
            p['dec']['W'] *= (w / 0.5) ** 0.5; p['dec']['L'] *= ((1 - w) / 0.5) ** 0.5
            if p['role'] == 'RP':
                p['dec']['SV'] *= (w / 0.5) ** 0.5; p['dec']['HLD'] *= (w / 0.5) ** 0.5
            p['team_w'] = round(w, 3)


# ------------------------------------------------------------------ prospect pedigree
def pedigree(T):
    """MLB Pipeline Top 100 (current list and each preseason). The best recent rank
    gives a bump to the good rates and to the chance of an MLB role."""
    import glob as _g
    from unicodedata import normalize
    nm = lambda s: re.sub(r'[^a-z]', '', normalize('NFKD', s).encode('ascii', 'ignore').decode().lower())
    by_name = collections.defaultdict(list)
    for p in T.values(): by_name[nm(p['name'])].append(p)
    best = {}
    for f in sorted(_g.glob(f'{H}/pipeline/*.json')):
        if '_net' in f: continue
        lab = os.path.basename(f)[:-5]
        rec = 1.0 if lab in ('current', 'preseason_2026') else 0.7 if lab == 'preseason_2025' else 0.4
        for r in load(f)['rows']:
            cands = [p for p in T.values() if p['id'] == r.get('id')] if r.get('id') else by_name.get(nm(r['name']), [])
            for p in cands:
                score = (101 - r['rank']) * rec
                if score > best.get(id(p), (0, None))[0]: best[id(p)] = (score, f"#{r['rank']} ({lab.replace('_', ' ')})")
    for p in T.values():
        b = best.get(id(p))
        if not b: continue
        p['pipeline'] = b[1]
        young = (p.get('mlb_pa') or p.get('mlb_bf') or 0) < 800
        if not young: continue
        bump = 1 + 0.06 * (b[0] / 100)          # up to +6% on the good rates for a recent #1 prospect
        r = p['rate']
        if p['role'] == 'H':
            for k in ('H', 'D', 'T', 'HR', 'R', 'RBI', 'BB', 'SB'): r[k] *= bump
        else:
            r['K'] *= bump
            for k in ('BB', 'HA', 'ER', 'HR'): r[k] /= bump
        if p.get('mlb_share', 1) < 1:
            p['mlb_share'] = round(min(1.0, p['mlb_share'] + 0.35 * (b[0] / 100)), 2)


# ------------------------------------------------------------------ fielding (assists, errors) and positions
POSMAP = {'LF': 'OF', 'CF': 'OF', 'RF': 'OF', 'OF': 'OF', 'C': 'C', '1B': '1B', '2B': '2B', '3B': '3B', 'SS': 'SS'}


def fielding(T):
    """Assists and errors per game played, 5/4/3 over MLB seasons, pulled toward the average
    at his main position (errors pulled harder: they are noisy). Also sets where he is eligible:
    any position with 10+ games in the latest season, plus his main one."""
    Y0 = max(SEASONS)
    fld = {}
    for y in SEASONS:
        f = f'{H}/fielding/{y}.json'
        if not os.path.exists(f): continue
        for x in load(f)['stats'][0]['splits']:
            pos = POSMAP.get(x['position']['abbreviation'])
            if not pos: continue
            st = x['stat']
            d = fld.setdefault(x['player']['id'], {}).setdefault(y, collections.Counter())
            d['A'] += st.get('assists', 0); d['E'] += st.get('errors', 0); d['g_' + pos] += st.get('gamesPlayed', 0)
    tot = collections.defaultdict(collections.Counter)      # league rates by main position
    main = {}
    for pid, ys in fld.items():
        g = collections.Counter()
        for y, d in ys.items():
            for k, v in d.items():
                if k.startswith('g_'): g[k[2:]] += SEASONS[y] * v
        if not g: continue
        main[pid] = g.most_common(1)[0][0]
        for y, d in ys.items():
            gy = sum(v for k, v in d.items() if k.startswith('g_'))
            tot[main[pid]]['A'] += d['A']; tot[main[pid]]['E'] += d['E']; tot[main[pid]]['G'] += gy
    lg = {pos: (c['A'] / max(c['G'], 1), c['E'] / max(c['G'], 1)) for pos, c in tot.items()}
    lg['DH'] = (0.0, 0.0)
    hit_g = {y: {pid: s['gamesPlayed'] for pid, (s, x) in rows(f'{H}/seasons/{y}_hitting.json').items()} for y in SEASONS}
    for key, p in T.items():
        if p['role'] != 'H': continue
        pid = p['id']; ys = fld.get(pid, {})
        prim = main.get(pid) or POSMAP.get(p.get('pos') or (people.get(pid) or {}).get('pos') or '', 'DH')
        A = sum(SEASONS[y] * d['A'] for y, d in ys.items()); E = sum(SEASONS[y] * d['E'] for y, d in ys.items())
        G = sum(SEASONS[y] * hit_g[y].get(pid, 0) for y in SEASONS)
        la, le = lg.get(prim, (0.0, 0.0))
        p['a_g'] = (A + FIELD_PRIOR_A * la) / (G + FIELD_PRIOR_A)
        p['e_g'] = (E + FIELD_PRIOR_E * le) / (G + FIELD_PRIOR_E)
        el = {pos for pos in ('C', '1B', '2B', '3B', 'SS', 'OF') if ys.get(Y0, {}).get('g_' + pos, 0) >= 10}
        if prim != 'DH': el.add(prim)
        p['el'] = el; p['prim'] = prim
        p['fld'] = {y: (d['A'], d['E']) for y, d in ys.items()}
    return lg
