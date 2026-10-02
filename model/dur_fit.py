"""Fit the durability pieces against the truth: what share of the next season was each established player off the IL?"""
import collections, re, pickle
import numpy as np
import talent, stress_lib as S
rows = []
def talent_group(p, eo, target):
    if not eo: return 'healthy'
    talent.IL_END = target - 1; g = talent.carry_group(p, eo); return g
for target in (2024, 2025, 2026):
    S.as_of(target)
    if target == 2024: talent.SEASONS = {2023: 5, 2022: 4}
    T, _ = talent.build(); talent.durability(T)
    end_open = dict(talent.END_OPEN[target - 1])
    S.reset(); talent.IL_END = target; talent.DUR_W = {target: 1}
    days, _ = talent.il_days(); act = talent.active_days()
    played = set(talent.rows(f'{talent.H}/seasons/{target}_hitting.json')) | set(talent.rows(f'{talent.H}/seasons/{target}_pitching.json'))
    S.reset()
    for key, p in T.items():
        pid = p['id']
        if not ((p.get('mlb_pa', 0) >= 600) or (p.get('mlb_bf', 0) >= 500)): continue
        il = days[pid][target]
        if pid not in played and not il: continue
        il = min(il, max(0, 186 - act.get((key[0], pid), {}).get(target, 0)))
        rows.append(dict(t=target, role=p['role'], pred=p['avail'], act=1 - il / 186, name=p['name'], age=p['age'], g=(talent_group(p, end_open.get(pid), target) if p['il_hist'].get(target - 1, 0) >= 15 else 'healthy'), num=p['_il'][0], den=p['_il'][1],
                         eo=end_open.get(pid) if p['il_hist'].get(target - 1, 0) >= 15 else None, lt=p.get('long_term')))
pickle.dump(rows, open('dur_rows.pkl', 'wb'))
print(len(rows))
