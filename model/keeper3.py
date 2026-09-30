"""Run 2027, then re-age everyone to 2028 and 2029 (same track record, a year older;
prospects more likely to be up) and combine into a 3-year keeper value."""
import datetime as dt, pickle, talent, value27 as V

def year(y):
    talent.AGE_DATE = dt.date(y, 7, 1)
    T, _ = talent.build(); talent.durability(T); talent.team_context(T); talent.pedigree(T)
    for p in T.values():
        if p.get('mlb_share', 1) < 1: p['mlb_share'] = round(min(1.0, p['mlb_share'] + 0.4 * (y - 2027)), 2)
    pool, meta = V.run(T)
    return {p['id'] if p['role'] == 'H' else -p['id']: p for p in pool}, meta

y27, meta = year(2027)
y28, _ = year(2028)
y29, _ = year(2029)
for k, p in y27.items():
    a = y28.get(k); b = y29.get(k)
    p['wp28'] = a['wp_season'] if a else 0.0
    p['wp29'] = b['wp_season'] if b else 0.0
    p['keep3'] = p['wp_season'] + 0.8 * p['wp28'] + 0.6 * p['wp29']
pool = list(y27.values())
pickle.dump((pool, meta), open('v27.pkl', 'wb'))
top = sorted(pool, key=lambda p: -p['wp_season'])
for n in ('Paul Skenes', 'Chris Sale', 'Edwin Díaz', 'Garrett Whitlock', 'Konnor Griffin', 'Bryce Harper', 'Kade Anderson', 'Logan Webb', 'Aaron Judge', 'Pete Crow-Armstrong', 'Nick Kurtz', 'Junior Caminero'):
    x = [(i + 1, p) for i, p in enumerate(top) if p['name'] == n and p['mlb_share'] > 0.1]
    if x:
        i, p = x[0]
        print(f"{n:20s} 2027 #{i:<4d} {100*p['wp_season']:5.2f}  keep3 {100*p['keep3']:5.2f}  avail {p['avail']:.2f} {p.get('pipeline','')}")
print('keeper top 15:', [p['name'] for p in sorted(pool, key=lambda p: -p['keep3'])[:15]])
