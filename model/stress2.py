"""Stress test 2: is the 'healthy %' honest?  Predicted availability made the October before,
against the share of the next season each player was really off the injured list."""
import collections, datetime as dt, re
import numpy as np
from scipy.stats import spearmanr
import talent, stress_lib as S

ARM = re.compile(r'elbow|forearm|ucl|ulnar|tommy john|flexor|shoulder|lat |labrum|rotator', re.I)
rows = []
for target in (2024, 2025, 2026):
    S.as_of(target)
    if target == 2024: talent.SEASONS = {2023: 5, 2022: 4}
    T, _ = talent.build(); talent.durability(T)
    end_open = dict(talent.END_OPEN[target - 1])
    # the truth for the target season
    S.reset(); talent.IL_END = target; talent.DUR_W = {target: 1}
    days, _ = talent.il_days(); act = talent.active_days()
    played = set(talent.rows(f'{talent.H}/seasons/{target}_hitting.json')) | set(talent.rows(f'{talent.H}/seasons/{target}_pitching.json'))
    S.reset()
    for key, p in T.items():
        pid = p['id']
        est = (p.get('mlb_pa', 0) >= 600) or (p.get('mlb_bf', 0) >= 500)
        if not est: continue
        il = days[pid][target]
        if pid not in played and not il: continue              # retired or released: not an injury question
        il = min(il, max(0, 186 - act.get((key[0], pid), {}).get(target, 0)))
        eo = end_open.get(pid)
        rows.append(dict(t=target, role=p['role'], pred=p['avail'], act=1 - il / 186, name=p['name'], age=p['age'],
                         eo=eo, lt=p.get('long_term')))
print('player-seasons checked:', len(rows))
for role in ('H', 'SP', 'RP'):
    rs = [r for r in rows if r['role'] == role]
    pr = np.array([r['pred'] for r in rs]); ac = np.array([r['act'] for r in rs])
    const = np.full(len(rs), ac.mean())
    print(f'\n{role}: n={len(rs)}  predicted avg {pr.mean():.3f}  actual avg {ac.mean():.3f}  rank corr {spearmanr(pr, ac)[0]:.3f}  '
          f'avg miss {np.abs(pr - ac).mean():.3f} (everyone-the-same guess: {np.abs(const - ac).mean():.3f})')
    qs = np.quantile(pr, [0, .1, .3, .7, .9, 1])
    for a, b in zip(qs[:-1], qs[1:]):
        m = (pr >= a) & (pr <= b)
        print(f'   predicted {a:.2f}-{b:.2f}: n={m.sum():4d}  predicted {pr[m].mean():.3f}  actual {ac[m].mean():.3f}')

print('\n--- players who finished the prior season on the injured list')
def grp(lab, f):
    rs = [r for r in rows if r['eo'] and f(r)]
    if not rs: return
    pr = np.mean([r['pred'] for r in rs]); ac = np.mean([r['act'] for r in rs])
    zero = np.mean([r['act'] < 0.25 for r in rs])
    print(f'   {lab:52s} n={len(rs):3d}  predicted {pr:.2f}  actual {ac:.2f}  missed 75%+ of next year: {100 * zero:.0f}%')
P = lambda r: r['role'] != 'H'
late = lambda r: r['eo'][0].month >= 6
grp('hitters, any reason', lambda r: not P(r))
grp('pitchers, any reason', P)
grp('pitchers, arm, went down June or later', lambda r: P(r) and late(r) and ARM.search(r['eo'][1]))
grp('pitchers, arm, went down before June', lambda r: P(r) and not late(r) and ARM.search(r['eo'][1]))
grp('pitchers, elbow/forearm only, June or later', lambda r: P(r) and late(r) and re.search(r'elbow|forearm|ucl|ulnar|flexor', r['eo'][1], re.I))
grp('pitchers, shoulder only, June or later', lambda r: P(r) and late(r) and re.search(r'shoulder|lat |labrum|rotator', r['eo'][1], re.I))
grp('pitchers, not arm', lambda r: P(r) and not ARM.search(r['eo'][1]))
grp('pitchers, on 60-day list at the end', lambda r: P(r) and '60-day' in r['eo'][1])
grp('pitchers, arm, 60-day, June or later', lambda r: P(r) and late(r) and ARM.search(r['eo'][1]) and '60-day' in r['eo'][1])
grp('pitchers, arm, 15-day only, Aug or later', lambda r: P(r) and r['eo'][0].month >= 8 and ARM.search(r['eo'][1]) and '60-day' not in r['eo'][1])
grp('hitters, 60-day at the end', lambda r: not P(r) and '60-day' in r['eo'][1])
grp('everyone the model flagged long-term', lambda r: r['lt'])
print('   (for scale) pitchers who finished healthy:', round(np.mean([r['act'] for r in rows if P(r) and not r['eo']]), 2),
      ' hitters who finished healthy:', round(np.mean([r['act'] for r in rows if not P(r) and not r['eo']]), 2))
