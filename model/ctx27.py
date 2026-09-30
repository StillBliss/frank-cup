"""2027 context: how the typical team's weekly totals change from 2026 rules to 2027 rules (12 teams)."""
import json, numpy as np, sim2 as S
TYP26, TYP27 = (10, 10, 3, 1), (10, 8, 2, 1)
lg26 = S.League(2026, TYP26); S.calibrate(lg26, TYP26, n=2000)
m26 = S.weeks_exp(lg26, TYP26, 4000).mean(axis=0)
lg27 = S.League(2027, TYP27)
m27 = S.weeks_exp(lg27, TYP27, 4000).mean(axis=0)
ratio = {k: float(m27[i] / m26[i]) if m26[i] else 1.0 for i, k in enumerate(S.KEYS)}
json.dump(ratio, open('ctx27.json', 'w'), indent=1)
print({k: round(v, 3) for k, v in ratio.items()})
