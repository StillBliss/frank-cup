"""
League records for the Records page and the Gazette.

Everything here is keeper era (2023 on, the seasons we have). Single-week category
records only count standard 7-day weeks: Yahoo stretches the opening week (5 to 20
days) and the All-Star break week (14 days), and those would swamp every counting
record. Grades are always relative to the rest of the league that same week, so
every week counts for those.
"""
import datetime as dt
from collections import defaultdict


def fnum(v):
    if isinstance(v, str) and "/" in v: return None
    try: return float(v)
    except (TypeError, ValueError): return None


def week_info(week_ranges):
    """{week: {"start", "end", "days", "standard"}} from {week: (start, end)}"""
    out = {}
    for w, (a, b) in sorted(week_ranges.items()):
        days = (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days + 1
        out[str(w)] = {"start": a, "end": b, "days": days, "standard": days == 7}
    return out


def week_grades(D, season, week):
    """same arithmetic as the site's plusWeek(): 100 = league average that week"""
    cats, lower = D["cats"], set(D["lowerBetter"])
    skip = set(D.get("nonScoring") or ["H/AB"])
    idx = [i for i, c in enumerate(cats) if c not in skip]
    lines = {}
    for m, weeks in (D["weeklyDetail"].get(str(season)) or {}).items():
        e = weeks.get(str(week))
        if e: lines[m] = e["you"]
    if len(lines) < 4: return {}
    acc = {m: {"H": [], "P": []} for m in lines}
    for i in idx:
        g = "H" if i < D["hitN"] else "P"
        lb = cats[i] in lower
        for m in lines:
            a = fnum(lines[m][i])
            if a is None: continue
            pts = n = 0
            for o in lines:
                if o == m: continue
                c = fnum(lines[o][i])
                if c is None: continue
                n += 1
                if a == c: pts += .5
                elif (a < c) if lb else (a > c): pts += 1
            if n: acc[m][g].append(pts / n)
    out = {}
    for m in lines:
        av = lambda a: 200 * sum(a) / len(a) if a else None
        H, P = av(acc[m]["H"]), av(acc[m]["P"])
        G = P if H is None else H if P is None else (H + P) / 2
        out[m] = {"G": G, "H": H, "P": P}
    return out


def _ladder(rows, key, low=False, distinct=4, cap=250):
    """every row tied for the record, plus the rows for the next few distinct values"""
    rows = sorted([r for r in rows if r.get(key) is not None], key=lambda r: r[key] if low else -r[key])
    out, seen = [], []
    for r in rows:
        if r[key] not in seen:
            if len(seen) == distinct: break
            seen.append(r[key])
        out.append(r)
        if len(out) >= cap: break
    return out


def week_allplay(D, season, week):
    """each team's matchup record that week against every other team's line"""
    cats, lower = D["cats"], set(D["lowerBetter"])
    skip = set(D.get("nonScoring") or ["H/AB"])
    idx = [i for i, c in enumerate(cats) if c not in skip]
    lines = {m: e["you"] for m, weeks in (D["weeklyDetail"].get(str(season)) or {}).items()
             for w, e in weeks.items() if w == str(week)}
    out = {}
    for me in lines:
        W = L = T = 0
        for o in lines:
            if o == me: continue
            cw = cl = 0
            for i in idx:
                a, b = fnum(lines[me][i]), fnum(lines[o][i])
                if a is None or b is None or a == b: continue
                if (a < b) if cats[i] in lower else (a > b): cw += 1
                else: cl += 1
            if cw > cl: W += 1
            elif cl > cw: L += 1
            else: T += 1
        out[me] = f"{W}-{L}-{T}"
    return out


def _top(rows, key, n, low=False):
    rows = [r for r in rows if r.get(key) is not None]
    rows.sort(key=lambda r: r[key] if low else -r[key])
    if not rows: return []
    cut = rows[min(n, len(rows)) - 1][key]
    return [r for r in rows if (r[key] <= cut if low else r[key] >= cut)]


def build_records(D, week_infos, n=5):
    cats, lower = D["cats"], set(D["lowerBetter"])
    skip = set(D.get("nonScoring") or ["H/AB"])
    years = sorted(D["seasons"])
    stage = {}      # (season, week, manager) -> "Regular" / "Playoff" / "Consolation"
    for s in years:
        br = (D.get("bracket") or {}).get(s) or {}
        live = set(br.get("live") or [])
        for r in D["seasons"][s]["matchups"]:
            if r["stage"] == "Regular": st = "Regular"
            else:
                k1, k2 = f"{r['week']}|{r['a']}|{r['b']}", f"{r['week']}|{r['b']}|{r['a']}"
                st = "Playoff" if (k1 in live or k2 in live) else "Consolation"
            stage[(s, r["week"], r["a"])] = stage[(s, r["week"], r["b"])] = st

    # ---- single weeks, standard 7-day weeks only
    single = {}
    for i, c in enumerate(cats):
        if c in skip: continue
        rows = []
        for s in years:
            wi = week_infos.get(s) or {}
            for m, weeks in (D["weeklyDetail"].get(s) or {}).items():
                for w, e in weeks.items():
                    if not (wi.get(w) or {}).get("standard"): continue
                    if stage.get((s, int(w), m)) == "Consolation": continue
                    v = fnum(e["you"][i])
                    if v is None: continue
                    rows.append({"m": m, "s": int(s), "w": int(w), "v": v,
                                 "stage": stage.get((s, int(w), m), "Regular")})
        single[c] = {"best": _ladder(rows, "v", low=c in lower)}

    # ---- seasons (regular season totals)
    season = {}
    for i, c in enumerate(cats):
        if c in skip: continue
        rows = []
        for s in years:
            for m, line in (D["seasons"][s].get("seasonStats") or {}).items():
                v = fnum(line[i])
                if v is not None: rows.append({"m": m, "s": int(s), "v": v})
        season[c] = {"best": _ladder(rows, "v", low=c in lower),
                     "worst": _top(rows, "v", 1, low=c not in lower)}

    # ---- grades, every week (relative, so odd lengths don't matter)
    gweeks = []
    for s in years:
        for w in sorted({int(w) for weeks in (D["weeklyDetail"].get(s) or {}).values() for w in weeks}):
            for m, g in week_grades(D, s, w).items():
                if stage.get((s, w, m)) == "Consolation": continue
                gweeks.append({"m": m, "s": int(s), "w": w, "stage": stage.get((s, w, m), "Regular"),
                               "G": g["G"], "H": g["H"], "P": g["P"]})
    for r in gweeks:
        for k in ("G", "H", "P"):
            if r[k] is not None: r[k] = round(r[k], 1)
    grades = {k: {"best": _top(gweeks, k, 10), "worst": _top(gweeks, k, 10, low=True)} for k in ("G", "H", "P")}

    # season average grade, regular season
    sg = defaultdict(list)
    for r in gweeks:
        if r["stage"] == "Regular" and r["G"] is not None: sg[(r["s"], r["m"])].append(r["G"])
    savg = [{"m": m, "s": s, "v": round(sum(v) / len(v), 1)} for (s, m), v in sg.items() if v]
    season_grade = {"best": _top(savg, "v", 5), "worst": _top(savg, "v", 5, low=True)}

    # ---- matchups
    games = []
    for s in years:
        for r in D["seasons"][s]["matchups"]:
            if r.get("live"): continue
            st = stage.get((s, r["week"], r["a"]), r["stage"])
            win = r.get("win") or (r["a"] if r["aw"] > r["al"] else r["b"] if r["al"] > r["aw"] else None)
            hi, lo = max(r["aw"], r["al"]), min(r["aw"], r["al"])
            games.append({"s": int(s), "w": r["week"], "stage": st, "a": r["a"], "b": r["b"],
                          "win": win, "lose": (r["b"] if win == r["a"] else r["a"]) if win else None,
                          "score": f"{hi}-{lo}-{r['at']}", "margin": hi - lo, "hi": hi,
                          "tied": r["aw"] == r["al"]})
    games = [g for g in games if g["stage"] != "Consolation"]
    blow = _top(games, "margin", 8)
    finals = []
    for s in years:
        fs = [g for g in games if g["s"] == int(s) and g["stage"] == "Playoff"]
        if not fs: continue
        last = max(g["w"] for g in fs)
        for g in fs:
            if g["w"] == last and (D.get("finalPlace") or {}).get(s):
                seeds = ((D.get("bracket") or {}).get(s) or {}).get("seeds") or {}
                g = dict(g, seedWin=seeds.get(g["win"]), seedLose=seeds.get(g["lose"]))
                finals.append(g)
    ties = [dict(g, seeds=((D.get("bracket") or {}).get(str(g["s"])) or {}).get("seeds", {}))
            for g in games if g["stage"] == "Playoff" and g["tied"]]
    for t in ties:
        t["seedWin"], t["seedLose"] = t["seeds"].get(t["win"]), t["seeds"].get(t["lose"])
        del t["seeds"]

    # ---- bad beats (great weeks that lost) and lucky weeks (bad weeks that won)
    gmap = {(r["s"], r["w"], r["m"]): r for r in gweeks}
    apw = {}
    for s_ in years:
        for w_ in sorted({int(w) for weeks in (D["weeklyDetail"].get(s_) or {}).values() for w in weeks}):
            for m, rec in week_allplay(D, s_, w_).items(): apw[(int(s_), w_, m)] = rec
    beats, lucky = [], []
    for g in games:
        if not g["win"] or g.get("live"): continue
        wg, lg = gmap.get((g["s"], g["w"], g["win"])), gmap.get((g["s"], g["w"], g["lose"]))
        if not wg or not lg or wg["G"] is None or lg["G"] is None: continue
        base = {"s": g["s"], "w": g["w"], "stage": g["stage"], "score": g["score"], "win": g["win"], "lose": g["lose"]}
        beats.append(dict(base, m=g["lose"], G=lg["G"], opp=g["win"], oppG=wg["G"], ap=apw.get((g["s"], g["w"], g["lose"]))))
        lucky.append(dict(base, m=g["win"], G=wg["G"], opp=g["lose"], oppG=lg["G"], ap=apw.get((g["s"], g["w"], g["win"]))))
    bad_beats = _top(beats, "G", 10)
    lucky_weeks = _top(lucky, "G", 10, low=True)

    # ---- season records: category record and matchup record, regular season
    srec = []
    for s in years:
        for r in D["seasons"][s]["standings"]:
            srec.append({"m": r["manager"], "s": int(s), "cat": [r["w"], r["l"], r["t"]],
                         "match": [r["mw"], r["ml"], r["mt"]], "pct": r["pct"],
                         "weeks": len(D["seasons"][s].get("weeks") or [])})
    best_season = _top(srec, "pct", 5)
    worst_season = _top(srec, "pct", 3, low=True)

    # ---- matchup win streaks, regular season, carried across seasons
    seq = defaultdict(list)
    for g in sorted(games, key=lambda g: (g["s"], g["w"])):
        if g["stage"] != "Regular": continue
        for m in (g["a"], g["b"]):
            seq[m].append(("T" if g["win"] is None else "W" if g["win"] == m else "L", g["s"], g["w"]))
    oc = D.get("ownerChanges") or {}
    runs = []
    for m, sq in seq.items():
        cur = None
        for res, s, w in sq:
            if cur and m in oc and cur["from"][0] < oc[m]["since"] <= s:
                if cur["k"] in "WL": runs.append(cur)     # a new owner starts a fresh streak
                cur = None
            if cur and cur["k"] == res: cur["n"] += 1; cur["to"] = [s, w]
            else:
                if cur and cur["k"] in "WL": runs.append(cur)
                cur = {"m": m, "k": res, "n": 1, "from": [s, w], "to": [s, w]}
        if cur and cur["k"] in "WL": runs.append(cur)
    win_runs = _top([r for r in runs if r["k"] == "W"], "n", 5)
    skids = _top([r for r in runs if r["k"] == "L"], "n", 5)

    lens = {s: len(D["seasons"][s].get("weeks") or []) for s in years}
    # flag records that belong to a franchise's previous owner
    def tag(x):
        if isinstance(x, dict):
            for k in ("m", "win", "lose", "a", "b"):
                v = x.get(k)
                if v in oc and x.get("s", 9999) < oc[v]["since"] and v not in x.get("prev", []):
                    x.setdefault("prev", []).append(v)
            for v in x.values(): tag(v)
        elif isinstance(x, list):
            for v in x: tag(v)
    out_all = [single, season, grades, season_grade, blow, finals, ties, best_season, worst_season, bad_beats, lucky_weeks, win_runs, skids]
    for r in win_runs + skids:
        if r["m"] in oc and r["from"][0] < oc[r["m"]]["since"]: r["prev"] = [r["m"]]
    for o in out_all[:-2]: tag(o)
    return {"era": f"{years[0]}-{years[-1]}", "single": single, "season": season, "grades": grades,
            "seasonGrade": season_grade, "blowouts": blow, "badBeats": bad_beats, "luckyWeeks": lucky_weeks, "finals": finals, "playoffTies": ties,
            "bestSeason": best_season, "worstSeason": worst_season, "winRuns": win_runs, "skids": skids,
            "regWeeks": lens,
            "oddWeeks": {s: [int(w) for w, x in (week_infos.get(s) or {}).items() if not x["standard"]] for s in years}}
