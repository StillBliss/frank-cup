"""
Playoff odds after every regular-season week, for the Trends page.

Uses the Gazette's own Monte Carlo (news.sim_odds). A finished week's odds never
change, so each one is computed once and cached in raw/<season>/odds.json; the
daily refresh only simulates the newest week.
"""
import json, os

N_SIMS = 1000
# tuned on 2023-2025: a team's whole-week hot/cold swing, and doubt about its true level
WK_SD, TEAM_SD = 0.15, 0.30


def history(D, cfg, raw):
    import news
    L = news.League(D=D, cfg=cfg)
    out = {}
    for y in L.seasons():
        path = os.path.join(raw, str(y), "odds.json")
        try:
            with open(path, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, ValueError):
            cache = {}
        po = L.po_start(y)
        done = [w for w in L.completed_weeks(y) if w < po]
        changed = False
        for w in done:
            if str(w) in cache: continue
            o = news.sim_odds(L, y, w, n=N_SIMS, wk_sd=WK_SD, team_sd=TEAM_SD)
            if not o: continue
            cache[str(w)] = {m: v["po"] for m, v in o.items()}
            changed = True
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cache, f, separators=(",", ":"))
        if cache:
            out[str(y)] = {w: cache[w] for w in sorted(cache, key=int)}
    return out
