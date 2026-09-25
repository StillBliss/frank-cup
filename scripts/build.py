"""Rebuild the dashboard's LEAGUE_DATA from raw Yahoo pulls."""
import json, os, sys
from collections import defaultdict
import build_core as bc

HERE = os.path.dirname(os.path.abspath(__file__))

def num(v):
    if v in ("", None, "-"): return 0
    if isinstance(v,(int,float)): return v
    if "/" in v: return v
    try:
        return int(v)
    except ValueError:
        return float(v)

class Season:
    def __init__(self, year, cfg):
        self.year = year
        self.meta, self.settings, cats = bc.settings(year)
        self.cats = cats
        self.teams = bc.teams(year)
        ids = cfg["teamIds"][str(year)]
        self.mgr = {k: ids[str(v["team_id"])] for k, v in self.teams.items()}
        self.names = {self.mgr[k]: v["name"] for k, v in self.teams.items()}
        self.po_start = int(self.settings.get("playoff_start_week") or 99)
        self.ms = bc.matchups(year)
        for m in self.ms:
            for t in m["teams"]:
                t["m"] = self.mgr[t["key"]]
        self.scoring = [c for c in cats if not c["display_only"]]
        self.reg = [m for m in self.ms if m["week"] < self.po_start and not m["playoffs"]]
        self.reg_weeks = sorted({m["week"] for m in self.reg if m["status"] == "postevent"})

    def cat_result(self, m):
        """per-team (w,l,t) of categories in a matchup"""
        a, b = m["teams"]
        r = {a["m"]: [0,0,0], b["m"]: [0,0,0]}
        for c in self.scoring:
            w = m["stat_winners"].get(c["id"])
            if w == "tie" or w is None:
                r[a["m"]][2]+=1; r[b["m"]][2]+=1
            elif w == a["key"]:
                r[a["m"]][0]+=1; r[b["m"]][1]+=1
            else:
                r[b["m"]][0]+=1; r[a["m"]][1]+=1
        return r

    def seeds(self):
        try:
            t = bc.L(f"{self.year}/standings.json")["fantasy_content"]["league"][1]["standings"][0]["teams"]
        except (KeyError, IndexError, FileNotFoundError):
            return {}
        out = {}
        for k in t:
            if not k.isdigit(): continue
            info = bc.flat(t[k]["team"][0])
            sd = t[k]["team"][2]["team_standings"].get("playoff_seed")
            if sd not in (None, ""): out[self.mgr[info["team_key"]]] = int(sd)
        return out

    def season_stats(self):
        t = bc.L(f"{self.year}/team_stats_season.json")["fantasy_content"]["league"][1]["teams"]
        out = {}
        for k in t:
            if not k.isdigit(): continue
            info = bc.flat(t[k]["team"][0])
            vals = {str(x["stat"]["stat_id"]): x["stat"]["value"] for x in t[k]["team"][1]["team_stats"]["stats"]}
            out[self.mgr[info["team_key"]]] = [num(vals.get(c["id"])) for c in self.cats]
        return out

    def res(self, m):
        a, b = m["teams"]
        aw = int(a["points"] or 0); al = int(b["points"] or 0)
        at = len(self.scoring) - aw - al
        return a["m"], b["m"], aw, al, at

    def split(self, m):
        """team a's (w,l,t) in hitting and in pitching categories, per Yahoo's stat winners"""
        a = m["teams"][0]
        h, p = [0,0,0], [0,0,0]
        for c in self.scoring:
            g = h if c["group"] == "batting" else p
            w = m["stat_winners"].get(c["id"])
            if w == "tie" or w is None: g[2] += 1
            elif w == a["key"]: g[0] += 1
            else: g[1] += 1
        return h, p

    def matchup_rows(self):
        seeds = self.seeds()
        out = []
        for m in self.ms:
            a, b, aw, al, at = self.res(m)
            h, p = self.split(m)
            r = {"week": m["week"], "stage": "Playoff" if m["playoffs"] else "Regular",
                 "a": a, "b": b, "aw": aw, "al": al, "at": at, "ah": h, "ap": p}
            if m["status"] != "postevent": r["live"] = True
            if m["playoffs"] and m["status"] == "postevent":
                # playoff games never tie: Yahoo names a winner, else the better seed advances
                win = self.mgr.get(m["winner"]) if m["winner"] else None
                if win is None:
                    if aw != al: win = a if aw > al else b
                    else: win = a if seeds.get(a, 99) <= seeds.get(b, 99) else b
                r["win"] = win
            out.append(r)
        return out

def gb_of(rec, lead):
    return ((lead[0]-rec[0]) + (rec[1]-lead[1])) / 2.0

def season_block(S):
    rows = S.matchup_rows()
    # standings (regular season, completed weeks only)
    cat = defaultdict(lambda: [0,0,0]); mat = defaultdict(lambda: [0,0,0])
    order = []
    prog = []
    heat = defaultdict(list)
    for wk in S.reg_weeks:
        for r in rows:
            if r["week"] != wk or r["stage"] != "Regular": continue
            for me, op, w, l, t in ((r["a"], r["b"], r["aw"], r["al"], r["at"]),
                                    (r["b"], r["a"], r["al"], r["aw"], r["at"])):
                if me not in order: order.append(me)
                c = cat[me]; c[0]+=w; c[1]+=l; c[2]+=t
                mm = mat[me]
                if w > l: mm[0]+=1
                elif l > w: mm[1]+=1
                else: mm[2]+=1
                heat[me].append(w)
        lead = max(order, key=lambda m: (cat[m][0]-cat[m][1]))
        gbs = {m: gb_of(cat[m], cat[lead]) for m in order}
        ranked = sorted(order, key=lambda m: (gbs[m], -cat[m][0]))
        prog.append({"week": wk, "gb": gbs, "rank": {m: i+1 for i, m in enumerate(ranked)}})
    seed = S.seeds()
    ranked = sorted(order, key=lambda m: (gb_of(cat[m], cat[ranked[0]]), seed.get(m, 99), -cat[m][0]))
    lead = cat[ranked[0]]
    standings = []
    for m in ranked:
        w,l,t = cat[m]
        standings.append({"manager": m, "team": S.names[m], "w": w, "l": l, "t": t,
                          "pct": round((w + t/2)/(w+l+t), 4), "gb": gb_of(cat[m], lead),
                          "mw": mat[m][0], "ml": mat[m][1], "mt": mat[m][2]})
    return {"rows": rows, "standings": standings, "prog": prog, "heat": dict(heat), "order": order}

def h2h_tables(managers, all_rows, stage_filter, cats=False, include_live=True):
    tab = {a: {b: {"w":0,"l":0,"t":0} for b in managers if b != a} for a in managers}
    for r in all_rows:
        if not stage_filter(r): continue
        if not include_live and r.get("live"): continue
        for me, op, w, l, t in ((r["a"], r["b"], r["aw"], r["al"], r["at"]),
                                (r["b"], r["a"], r["al"], r["aw"], r["at"])):
            x = tab[me][op]
            if cats:
                x["w"]+=w; x["l"]+=l; x["t"]+=t
            elif r.get("win"):
                x["w" if r["win"] == me else "l"] += 1
            else:
                if w>l: x["w"]+=1
                elif l>w: x["l"]+=1
                else: x["t"]+=1
    return tab

def cmp_val(c, x, y, lower):
    def f(v):
        if v in ("", None, "-"): return None
        try: return float(v)
        except ValueError: return None
    a, b = f(x), f(y)
    if a is None or b is None or a == b: return 0
    if lower: return 1 if a < b else -1
    return 1 if a > b else -1

def weekly_allplay(S, lowerBetter):
    """returns (catAllPlay byWeek, weekAllPlay byWeek) over regular completed weeks"""
    cat_weeks, wk_weeks = [], []
    for wk in S.reg_weeks:
        teams = []
        for m in S.ms:
            if m["week"] == wk and not m["playoffs"]:
                teams += m["teams"]
        cr, wr = {}, {}
        for me in teams:
            c = [0,0,0]; w = [0,0,0]
            for op in teams:
                if op is me: continue
                g = [0,0,0]
                for cat in S.scoring:
                    r = cmp_val(cat["id"], me["stats"].get(cat["id"]), op["stats"].get(cat["id"]), cat["abbr"] in lowerBetter)
                    g[0 if r>0 else 1 if r<0 else 2] += 1
                c = [c[i]+g[i] for i in range(3)]
            cr[me["m"]] = {"w":c[0],"l":c[1],"t":c[2]}
            w = [0,0,0]
            for op in teams:
                if op is me: continue
                a, b = int(me["points"] or 0), int(op["points"] or 0)
                w[0 if a>b else 1 if b>a else 2] += 1
            wr[me["m"]] = {"w":w[0],"l":w[1],"t":w[2]}
        cat_weeks.append({"week": wk, "records": cr}); wk_weeks.append({"week": wk, "records": wr})
    return cat_weeks, wk_weeks

def sum_weeks(byweek, order=None):
    out = {m: {"w":0,"l":0,"t":0} for m in (order or (byweek[0]["records"] if byweek else []))}
    for w in byweek:
        for m, r in w["records"].items():
            for k in "wlt": out[m][k] += r[k]
    return out

def fnum(v):
    if isinstance(v, str) and ("/" in v or v == ""): return v
    try: return float(v)
    except (TypeError, ValueError): return v

def weekly_detail(S):
    out = {}
    for m in S.ms:
        a, b, aw, al, at = S.res(m)
        for me, op, t, w, l in ((a, b, m["teams"][0], aw, al), (b, a, m["teams"][1], al, aw)):
            out.setdefault(me, {})[str(m["week"])] = {
                "opponent": op, "you": [fnum(t["stats"].get(c["id"])) for c in S.cats],
                "result": "W" if w > l else "L" if l > w else "T"}
    return out


def rnd(x):
    """round half away from zero (Python's round() is banker's rounding)"""
    import math
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)

def draws(S, cat_ap, wk_ap, lowerBetter):
    n = None
    act_c = {}; act_m = {}
    for m in S.ms:
        if m["week"] not in S.reg_weeks or m["playoffs"]: continue
        a, b = m["teams"]
        g = [0,0,0]
        for c in S.scoring:
            r = cmp_val(c["id"], a["stats"].get(c["id"]), b["stats"].get(c["id"]), c["abbr"] in lowerBetter)
            g[0 if r>0 else 1 if r<0 else 2] += 1
        for me, gg in ((a["m"], g), (b["m"], [g[1], g[0], g[2]])):
            x = act_c.setdefault(me, [0,0,0])
            for i in range(3): x[i] += gg[i]
        _, _, aw, al, at = S.res(m)
        for me, w, l in ((a["m"], aw, al), (b["m"], al, aw)):
            x = act_m.setdefault(me, [0,0,0])
            x[0 if w>l else 1 if l>w else 2] += 1
    opp = 0
    dc, dw = {}, {}
    for me in act_c:
        k = len([1 for _ in act_c]) - 1
        ap = cat_ap[me]; exp = [ap["w"]/k, ap["l"]/k, ap["t"]/k]
        a = act_c[me]
        dc[me] = {"act": a, "exp": [rnd(v) for v in exp],
                  "draw": rnd((a[0] + a[2]/2) - (exp[0] + exp[2]/2))}
        ap = wk_ap[me]; exp = [ap["w"]/k, ap["l"]/k, ap["t"]/k]
        a = act_m[me]
        dw[me] = {"act": a, "exp": [rnd(v) for v in exp],
                  "draw": rnd((a[0] + a[2]/2) - (exp[0] + exp[2]/2))}
    return dc, dw

def pct(r):
    tot = sum(r)
    return round((r[0] + r[2]/2)/tot, 4) if tot else 0.0

def lifetime(managers, per_season):
    """per_season: {year: {"standings":[...], "allPlay":{m:{}}, "weekAllPlay":{m:{}}}}"""
    out = []
    for m in managers:
        ap=[0,0,0]; wap=[0,0,0]; cat=[0,0,0]; mat=[0,0,0]; by={}
        for y, d in per_season.items():
            st = next((r for r in d["standings"] if r["manager"] == m), None)
            if not st: continue
            for arr, src in ((ap, d["allPlay"].get(m)), (wap, d["weekAllPlay"].get(m))):
                if src:
                    arr[0]+=src["w"]; arr[1]+=src["l"]; arr[2]+=src["t"]
            c=[st["w"],st["l"],st["t"]]; mm=[st["mw"],st["ml"],st["mt"]]
            for i in range(3): cat[i]+=c[i]; mat[i]+=mm[i]
            by[str(y)] = {"cat": c, "match": mm}
        out.append({"allPlay": ap, "allPlayPct": pct(ap), "weekAllPlay": wap, "weekAllPlayPct": pct(wap),
                    "manager": m, "cat": cat, "catPct": pct(cat), "match": mat, "matchPct": pct(mat),
                    "bySeason": by})
    out.sort(key=lambda r: -r["catPct"])
    return out

def season_done(S):
    end = int(S.meta.get("end_week") or 0)
    last = [m for m in S.ms if m["week"] == end]
    return bool(last) and all(m["status"] == "postevent" for m in last)

def reg_done(S):
    reg = [m for m in S.ms if not m["playoffs"]]
    return bool(reg) and all(m["status"] == "postevent" for m in reg) and \
        max(m["week"] for m in reg) >= S.po_start - 1

def final_places(S):
    t = bc.L(f"{S.year}/standings.json")["fantasy_content"]["league"][1]["standings"][0]["teams"]
    rows = []
    for k in t:
        if not k.isdigit(): continue
        info = bc.flat(t[k]["team"][0])
        rows.append((int(t[k]["team"][2]["team_standings"]["rank"]), S.mgr[info["team_key"]]))
    return [m for _, m in sorted(rows)]

def postseason_and_bracket(S):
    seeds = S.seeds()
    seeds = dict(sorted(seeds.items(), key=lambda kv: kv[1]))
    nteams = int(S.settings.get("num_playoff_teams") or 6)
    field = [m for m, s in seeds.items() if s <= nteams]
    end = int(S.meta.get("end_week") or 0)
    labels = {end: "Final", end-1: "Semifinal", end-2: "Quarterfinal"}
    post, live, dead = [], [], []
    alive = set(field)
    for wk in sorted({m["week"] for m in S.ms if m["playoffs"]}):
        losers = set()
        for m in [m for m in S.ms if m["playoffs"] and m["week"] == wk]:
            a, b, aw, al, at = S.res(m)
            win = S.mgr.get(m["winner"]) if m["winner"] else None
            if win is None:
                if aw != al: win = a if aw > al else b
                else: win = a if seeds.get(a, 99) <= seeds.get(b, 99) else b
            lose = b if win == a else a
            ws, ls = (aw, al) if win == a else (al, aw)
            g = {"season": S.year, "week": wk, "stage": "Playoff",
                 "game": labels.get(wk, "Playoff"), "winner": win, "ws": ws,
                 "loser": lose, "ls": ls}
            if m["status"] != "postevent": g["live"] = True
            post.append(g)
            key = f"{wk}|{a}|{b}"
            if a in alive and b in alive and not m["consolation"]:
                live.append(key)
                if m["status"] == "postevent": losers.add(lose)
            else:
                dead.append(key)
        alive -= losers
    return post, {"field": field, "live": live, "dead": dead, "seeds": seeds}

def payouts(managers, seasons, rules):
    """seasons: list of (year, standings, reg_done, champion or None)"""
    out = {m: {"total": 0, "bySeason": {}} for m in managers}
    for y, st, rdone, champ in seasons:
        amt = defaultdict(int)
        if rdone:
            for i, key in enumerate(("reg1", "reg2", "reg3")):
                if i < len(st): amt[st[i]["manager"]] += rules[key]
        if champ: amt[champ] += rules["champ"]
        for m, v in amt.items():
            out[m]["bySeason"][str(y)] = v
            out[m]["total"] += v
    return out

def trades_of(S, txs):
    out = []
    for t in txs:
        if t["type"] != "trade" or t["status"] != "successful": continue
        got = {}
        for p in t["players"]:
            if not p.get("destination_team_key") or not p.get("source_team_key"): continue
            got.setdefault(S.mgr[p["destination_team_key"]], []).append(
                {"player": p["name"], "pos": p["pos"], "from": S.mgr[p["source_team_key"]]})
        if len(got) < 2: continue   # one-sided (draft picks etc.)
        out.append({"season": S.year, "ts": t["ts"],
                    "parties": sorted([S.mgr[t["trader"]], S.mgr[t["tradee"]]]), "got": got})
    return out

def week_ranges(S):
    wr = {}
    for f in __import__("glob").glob(os.path.join(bc.RAW, str(S.year), "scoreboard", "week_*.json")):
        d = json.load(open(f, encoding="utf-8"))
        try:
            ms = d["fantasy_content"]["league"][1]["scoreboard"]["0"]["matchups"]
            m = ms["0"]["matchup"]
            wr[int(m["week"])] = (m["week_start"], m["week_end"])
        except (KeyError, IndexError, TypeError):
            pass
    return wr

def ts_week(ts, wr):
    import datetime as dt
    d = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat()
    for w, (a, b) in wr.items():
        if a <= d <= b: return w
    return None

def moves_of(S, txs, managers):
    wr = week_ranges(S)
    mv = {}
    adds = defaultdict(lambda: defaultdict(int)); drops = defaultdict(lambda: defaultdict(int))
    pos = {}
    for t in txs:
        if t["type"] not in ("add", "drop", "add/drop") or t["status"] != "successful": continue
        w = ts_week(t["ts"], wr)
        for p in t["players"]:
            if p["type"] == "add": m = S.mgr.get(p["destination_team_key"]); k = "add"
            elif p["type"] == "drop": m = S.mgr.get(p["source_team_key"]); k = "drop"
            else: continue
            if m is None: continue
            pos[p["name"]] = p["pos"]
            (adds if k == "add" else drops)[m][p["name"]] += 1
            if w is None: continue
            x = mv.setdefault(m, {}).setdefault(str(w), {"add": 0, "drop": 0}); x[k] += 1
    mv = {m: mv[m] for m in managers if m in mv}
    return mv, adds, drops, pos

def top(counter, n=8, pos=None):
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    if pos is None:
        return [{"player": k, "n": v} for k, v in items]
    return [{"player": k, "n": v, "pos": pos.get(k)} for k, v in items]

def players_by_season(S, adds, drafts, managers):
    out = {}
    for m in managers:
        picks = sorted([d for d in drafts if S.mgr.get(d["team"]) == m], key=lambda d: d["pick"])
        out[m] = {"added": top(adds.get(m, {})), "addTotal": sum(adds.get(m, {}).values()),
                  "draft": [{"round": d["round"], "pick": d["pick"], "player": d["player"], "pos": d["pos"]} for d in picks[:8]],
                  "draftTotal": len(picks)}
    return out

def players_lifetime(managers, seasons_data, P, cap=8):
    """seasons_data: list of (year, S, adds, drops, drafts); P = global first-seen positions"""
    out = {}
    for m in managers:
        dseas = defaultdict(list); dpos = {}
        A = defaultdict(int); Dr = defaultdict(int)
        cnt = 0
        for y, S, adds, drops, drafts in seasons_data:
            for d in drafts:
                if S.mgr.get(d["team"]) != m: continue
                cnt += 1
                dseas[d["player"]].append(y)
            for k, v in adds.get(m, {}).items(): A[k] += v
            for k, v in drops.get(m, {}).items(): Dr[k] += v
        rep = [(k, v) for k, v in dseas.items() if len(v) >= 2]
        rep.sort(key=lambda kv: (-len(kv[1]), kv[0]))
        out[m] = {"draftedRepeat": [{"player": k, "seasons": v, "pos": P.get(k)} for k, v in rep[:cap]],
                  "draftCount": cnt, "added": top(A, 8, P), "dropped": top(Dr, 8, P)}
    return out


# ------------------------------------------------------------------ assemble
def build(raw_dir, cfg):
    bc.RAW = raw_dir
    managers = cfg["managers"]
    ids = cfg["teamIds"]
    years = []
    for y in bc.seasons_available():
        if str(y) not in ids:
            prev = [int(k) for k in ids if int(k) < y]
            if not prev:
                continue
            ids[str(y)] = dict(ids[str(max(prev))])
            print(f"NOTE: no team mapping for {y}; reusing {max(prev)}'s. Check league_config.json.")
        years.append(y)
    ok = []
    for y in years:
        try:
            if Season(y, cfg).reg_weeks:
                ok.append(y)
        except (FileNotFoundError, KeyError) as e:
            print(f"skipping {y}: {e}")
    years = ok
    lower = cfg["lowerBetter"]
    D = {"managers": managers, "colors": cfg["colors"]}
    seasons, ap_all, wap_all, per, drawC, drawW = {}, {}, {}, {}, {}, {}
    rows_all, post_all, trades, moves, pbs, wdet = [], [], [], {}, {}, {}
    champ_rows = []  # championship bracket games only, consolation excluded
    brackets, finals, seeds_done, pay_in, sdata, ev = {}, {}, {}, [], [], []
    S_last = None
    for y in years:
        S = Season(y, cfg); S_last = S
        blk = season_block(S)
        seasons[str(y)] = {"teamNames": S.names, "weeks": S.reg_weeks, "standings": blk["standings"],
                           "progression": blk["prog"], "matchups": blk["rows"],
                           "seasonStats": S.season_stats(),
                           "heatmap": {m: blk["heat"][m] for m in managers if m in blk["heat"]}}
        for r in blk["rows"]: rows_all.append(r)
        cw, ww = weekly_allplay(S, lower)
        ap_all[str(y)] = {"season": sum_weeks(cw), "byWeek": cw}
        wap_all[str(y)] = {"season": sum_weeks(ww, [m for m in managers if ww and m in ww[0]["records"]]), "byWeek": ww}
        per[y] = {"standings": blk["standings"], "allPlay": ap_all[str(y)]["season"], "weekAllPlay": wap_all[str(y)]["season"]}
        drawC[str(y)], drawW[str(y)] = draws(S, ap_all[str(y)]["season"], wap_all[str(y)]["season"], lower)
        post, br = postseason_and_bracket(S)
        post_all += post; brackets[str(y)] = br
        ck = set(br["live"])
        for r in blk["rows"]:
            if r["stage"] == "Playoff" and (f"{r['week']}|{r['a']}|{r['b']}" in ck or f"{r['week']}|{r['b']}|{r['a']}" in ck):
                champ_rows.append(r)
        done = season_done(S)
        if done:
            finals[str(y)] = final_places(S); seeds_done[str(y)] = br["seeds"]
        pay_in.append((y, blk["standings"], reg_done(S), finals[str(y)][0] if done else None))
        txs = bc.transactions(y)
        trades += trades_of(S, txs)
        mv, ad, dr, _ = moves_of(S, txs, managers)
        moves[str(y)] = mv
        drafts = bc.draft(y)
        pbs[str(y)] = players_by_season(S, ad, drafts, managers)
        sdata.append((y, S, ad, dr, drafts))
        dts = int(S.settings.get("draft_time") or 0)
        for d in drafts: ev.append((dts, d["pick"], d["player"], d["pos"]))
        for t in txs:
            for p in t["players"]: ev.append((t["ts"], 0, p["name"], p["pos"]))
        wdet[str(y)] = weekly_detail(S)
    P = {}
    for e in sorted(ev, key=lambda e: (e[0], e[1])):
        P.setdefault(e[2], e[3])
    trades.sort(key=lambda t: t["ts"])
    cats = [c["abbr"] for c in S_last.cats]
    D["cats"] = cats
    D["hitN"] = sum(1 for c in S_last.cats if c["group"] == "batting")
    D["lowerBetter"] = lower
    D["seasons"] = seasons
    cur = years[-1]
    D["meta"] = {"currentSeason": cur,
                 "note": f"Live from the Yahoo Fantasy API. Seasons {years[0]}\u2013{years[-1]}.",
                 "updated": cfg.get("_updated")}
    if D["meta"]["updated"] is None: del D["meta"]["updated"]
    D["h2h"] = h2h_tables(managers, rows_all, lambda r: r["stage"] == "Regular")
    D["h2hPlayoff"] = h2h_tables(managers, champ_rows, lambda r: True, include_live=False)
    D["h2hCats"] = h2h_tables(managers, rows_all, lambda r: r["stage"] == "Regular", cats=True)
    D["weekAllPlay"] = wap_all
    D["trades"] = trades
    D["playersBySeason"] = pbs
    D["moves"] = moves
    D["nonScoring"] = [c["abbr"] for c in S_last.cats if c["display_only"]]
    D["lifetime"] = lifetime(managers, per)
    D["postseason"] = post_all
    D["bracket"] = brackets
    D["finalPlace"] = finals
    D["seeds"] = seeds_done
    D["payouts"] = payouts(managers, pay_in, cfg["payoutRules"])
    D["payoutRules"] = cfg["payoutRules"]
    D["weeklyDetail"] = wdet
    D["weeklyDetailNote"] = "Per-category detail for every manager, every week, straight from the Yahoo Fantasy API."
    D["allPlay"] = ap_all
    D["players"] = players_lifetime(managers, sdata, P)
    D["attribution"] = "Fantasy data provided by Yahoo Fantasy"
    D["drawCats"] = drawC
    D["drawWeeks"] = drawW
    awards = cfg.get("awards", {})
    D["awards"] = {str(y): awards.get(str(y), {}) for y in years}
    return D


def write_js(D, path):
    body = json.dumps(D, ensure_ascii=False, separators=(",", ":"))
    with open(path, "w", encoding="utf-8") as f:
        f.write("const LEAGUE_DATA = " + body + ";\n")

if __name__ == "__main__":
    root = os.path.dirname(HERE)
    cfg_path = os.path.join(root, "league_config.json")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    raw = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "raw")
    D = build(raw, cfg)
    try:
        import odds_history
        D["oddsByWeek"] = odds_history.history(D, cfg, raw)
    except Exception as e:  # noqa: BLE001
        print("playoff odds skipped:", repr(e))
    write_js(D, os.path.join(root, "data.js"))
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print("wrote data.js:", ", ".join(D["seasons"]))
