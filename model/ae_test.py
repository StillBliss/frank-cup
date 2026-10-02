import json, glob, sys, numpy as np
sys.path.insert(0, '/home/claude/frank-cup/scripts'); import sources
import model as M
from model import norm
WEEKS = 26.9
players, meta = M.build('2026_season', None, min_pa=1, min_gs=1, min_rp=1, season_weeks=WEEKS)
avg, repl = meta['avg'], meta['repl']
_, opp, _ = M.baseline()
yb = {}
for i, p in enumerate([p for f in sorted(glob.glob('/home/claude/research/research_out/season_B_*.json')) for p in sources._players(json.load(open(f)))]):
    f = lambda v: float(v) if v not in (None, '', '-') else 0.0
    yb.setdefault(norm(p['n']), (i + 1, f(p['s'].get('52')), f(p['s'].get('53')), p['pos'] or ''))
H = [p for p in players if p['role'] == 'H' and norm(p['name']) in yb]
H.sort(key=lambda p: -p['wp'])
for p in H: _, p['A'], p['E'], p['ypos'] = yb[norm(p['name'])]
band = H[100:130]
rA, rE = np.mean([p['A'] for p in band]) / WEEKS, np.mean([p['E'] for p in band]) / WEEKS
print('replacement hitter per week: A', round(rA, 2), 'E', round(rE, 2), '| avg team A', round(avg['A'], 1), 'E', round(avg['E'], 2))
base = M.score(M.swap(avg, repl['H'], repl['H']), opp)
out = []
for p in H[:250]:
    c = M.swap(avg, repl['H'], p['line'])
    c['A'] = avg['A'] - rA + p['A'] / WEEKS; c['E'] = max(0, avg['E'] - rE + p['E'] / WEEKS)
    cw, wp, per = M.score(c, opp)
    p['wp_ae'] = wp - base[1]; p['dA'] = per['A'] - base[2]['A']; p['dE'] = per['E'] - base[2]['E']
    out.append(p)
r0 = {id(p): i + 1 for i, p in enumerate(sorted(out, key=lambda p: -p['wp']))}
r1 = {id(p): i + 1 for i, p in enumerate(sorted(out, key=lambda p: -p['wp_ae']))}
yr = {id(p): yb[norm(p['name'])][0] for p in out}
top = [p for p in out if r0[id(p)] <= 150]
def corr(a, b):
    from scipy.stats import spearmanr
    return spearmanr([a[id(p)] for p in top], [b[id(p)] for p in top])[0]
print('rank agreement with Yahoo (top 150 hitters): without A/E', round(corr(r0, yr), 3), ' with A/E', round(corr(r1, yr), 3))
print('avg rank change when A/E added:', round(np.mean([abs(r0[id(p)] - r1[id(p)]) for p in top]), 1), 'spots')
by = {}
for p in top:
    k = 'MI/3B' if any(x in p['ypos'] for x in ('SS', '2B', '3B')) else 'C/1B' if any(x in p['ypos'] for x in ('C', '1B')) else 'OF/Util'
    by.setdefault(k, []).append(100 * (p['wp_ae'] - p['wp']))
print({k: (round(np.mean(v), 2), len(v)) for k, v in by.items()})
print('biggest gainers:', [(p['name'], r0[id(p)], r1[id(p)], int(p['A']), int(p['E'])) for p in sorted(top, key=lambda p: r1[id(p)] - r0[id(p)])[:8]])
print('biggest losers:', [(p['name'], r0[id(p)], r1[id(p)], int(p['A']), int(p['E'])) for p in sorted(top, key=lambda p: r0[id(p)] - r1[id(p)])[:8]])
p = [p for p in out if p['name'] == 'CJ Abrams'][0]
print('Abrams', r0[id(p)], r1[id(p)], 'A effect', round(100 * p['dA'], 1), 'E effect', round(100 * p['dE'], 1), 'net win%', round(100 * (p['wp_ae'] - p['wp']), 2))
