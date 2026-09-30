import json, sys, numpy as np
sys.path.insert(0, '.')
import sim2 as S
from model import norm
rng = np.random.default_rng(26)
REPO = '/home/claude/frank-cup'
s = open(f'{REPO}/data.js').read(); D = json.loads(s[s.index('{'):s.rindex('}') + 1])
print('seeds', (D.get('bracket', {}).get('2026') or {}).get('seeds'))
cats = D['cats']; low = set(D['lowerBetter'])
cur = {m: dict(zip(cats, D['weeklyDetail']['2026'][m]['26']['you'])) for m in ('Benny', 'Andrew')}
def comp(c):
    h, ab = map(float, c['H/AB'].split('/'))
    ip = S.ip if False else None
    a, _, b = str(c['IP']).partition('.'); ipv = int(a) + int(b or 0) / 3
    dbl = c['XBH'] - c['3B'] - c['HR']; tb = h + dbl + 2 * c['3B'] + 3 * c['HR']
    pao = (ab + c['BB']) * 1.02; ob = (c['OPS'] - tb / ab) * pao
    return dict(H=h, AB=ab, R=c['R'], T3=c['3B'], HR=c['HR'], RBI=c['RBI'], SB=c['SB'], BB=c['BB'], A=c['A'], E=c['E'],
                XBH=c['XBH'], TB=tb, OB=ob, PAO=pao, IP=ipv, W=c['W'], L=c['L'], CG=c['CG'], SV=c['SV'], K=c['K'],
                HLD=c['HLD'], ER=c['ERA'] * ipv / 9, BR=c['WHIP'] * ipv, BBP=c['K'] / c['K/BB'] if c['K/BB'] else 0, QS=c['QS'])
base = {m: comp(cur[m]) for m in cur}
print({m: {k: round(v, 1) for k, v in base[m].items()} for m in base})

# per-game / per-start / per-appearance lines from the model
byname = {}
for r in ('H', 'SP', 'RP'):
    for p in [p for p in S.players if p['role'] == r]:
        byname[(('H' if r == 'H' else 'P'), norm(p['name']))] = (S.unit(p), r)
K = S.KEYS
def line(side, name, fallback):
    v = byname.get((side, norm(name)))
    if v is None: print('   no model line for', name, '-> using', fallback); return fallback
    return v[0]
fa_sp = np.mean([x['u'] for x in S.POOL['SP'][110:140]], axis=0)
fa_rp = np.mean([x['u'] for x in S.POOL['RP'][40:70]], axis=0)
fa_h = np.mean([x['u'] for x in S.POOL['H'][100:140]], axis=0)

TEAM = {
 'Benny': dict(H=['Ben Rice', 'TJ Rumfield', 'Luis García Jr.', 'Munetaka Murakami', 'CJ Abrams', 'Fernando Tatis Jr.', 'Corbin Carroll', 'Kyle Schwarber', 'Coby Mayo', 'Henry Bolte'],
               SP=['Tanner Bibee', 'Quinn Mathews', 'Ryan Johnson', 'Yusei Kikuchi', 'Dean Kremer'],
               RP=["Riley O'Brien", 'Tanner Scott', 'Jeff Hoffman'], A=21 / 5, E=0.3),
 'Andrew': dict(H=['Hunter Goodman', 'Sal Stewart', 'Ketel Marte', 'Miguel Vargas', 'Geraldo Perdomo', 'Pete Crow-Armstrong', 'Jake McCarthy', 'Jordan Walker', 'Roman Anthony', 'Francisco Lindor'],
                SP=['Zack Wheeler', 'Anthony Kay', '__third__', '__stream__'],
                RP=['Jacob Latz', 'Tyler Rogers'], A=28 / 5, E=0.5),
}
third = np.mean([line('P', n, fa_sp) for n in ['Ranger Suarez', 'David Peterson', 'Jacob deGrom', 'Cam Schlittler', 'Brandon Pfaadt', 'Chris Bassitt']], axis=0)
def lines(m):
    t = TEAM[m]
    H = [line('H', n, fa_h) for n in t['H']]
    SP = [third if n == '__third__' else fa_sp if n == '__stream__' else line('P', n, fa_sp) for n in t['SP']]
    RP = [line('P', n, fa_rp) for n in t['RP']]
    return H, SP, RP
L = {m: lines(m) for m in TEAM}

def realize(m):
    H, SP, RP = L[m]
    tot = np.zeros(len(K))
    for day in range(2):
        for h in H:
            if rng.random() < 0.92: tot += h
        for r in RP:
            if rng.random() < 0.40: tot += r
    for sp in SP: tot += sp
    t = S.noisy(S.apply_cal(tot))
    return t

def score(n=20000):
    res = {'Benny': 0, 'Andrew': 0, 'tie': 0}; flip = {c: [0, 0, 0] for c in cats if c != 'H/AB'}
    margins = []
    for _ in range(n):
        tot = {}
        for m in TEAM:
            r = dict(zip(K, realize(m))); b = base[m]
            c = {k: b[k] + r.get(k, 0) for k in ('H', 'AB', 'R', 'HR', 'RBI', 'SB', 'BB', 'XBH', 'TB', 'OB', 'PAO', 'IP', 'W', 'L', 'CG', 'SV', 'K', 'HLD', 'ER', 'BR', 'BBP', 'QS')}
            c['3B'] = b['T3'] + r['3B']
            c['A'] = b['A'] + rng.poisson(TEAM[m]['A'] * 2 * 0.92); c['E'] = b['E'] + rng.poisson(TEAM[m]['E'] * 2)
            tot[m] = {'R': c['R'], '3B': c['3B'], 'HR': c['HR'], 'RBI': c['RBI'], 'SB': c['SB'], 'BB': c['BB'], 'A': c['A'], 'E': c['E'],
                      'AVG': round(c['H'] / c['AB'], 3), 'OPS': round(c['OB'] / c['PAO'] + c['TB'] / c['AB'], 3), 'XBH': c['XBH'],
                      'IP': round(c['IP'] * 3) / 3, 'W': c['W'], 'L': c['L'], 'CG': c['CG'], 'SV': c['SV'], 'K': c['K'], 'HLD': c['HLD'],
                      'ERA': round(9 * c['ER'] / c['IP'], 2), 'WHIP': round(c['BR'] / c['IP'], 2), 'K/BB': round(c['K'] / max(c['BBP'], 1e-9), 2), 'QS': c['QS']}
        bw = aw = 0
        for cname in flip:
            x, y = tot['Benny'][cname], tot['Andrew'][cname]
            if x == y: flip[cname][2] += 1
            elif (x < y) == (cname in low): flip[cname][0] += 1; bw += 1
            else: flip[cname][1] += 1; aw += 1
        margins.append(bw - aw)
        res['Benny' if bw > aw else 'Andrew' if aw > bw else 'tie'] += 1
    return res, flip, np.array(margins), n
res, flip, mg, n = score()
print({k: round(100 * v / n, 1) for k, v in res.items()})
for c, (b, a, t) in flip.items(): print(f"{c:5s} Benny {100*b/n:5.1f}  Andrew {100*a/n:5.1f}  tie {100*t/n:5.1f}")
import collections; print(sorted(collections.Counter(mg).items()))
